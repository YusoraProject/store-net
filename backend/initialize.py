"""首次启动创建空库；后续启动只检查结构、补齐初始账号，不修改已有表。"""
import json
from pathlib import Path

from sqlalchemy import MetaData, inspect, select, UniqueConstraint

from .database import Base, engine, SessionLocal
from .access_models import AccessBase
from .models import Role, User
from .auth import PERMISSIONS
from .config import ADMIN_USERNAME, ADMIN_EMAIL, ADMIN_PASSWORD
from .security import hash_password


def current_metadata():
    # 普通业务与门锁表统一建好，不再把门锁当作后续补装模块。
    metadata = MetaData()
    for source in (Base.metadata, AccessBase.metadata):
        for table in source.sorted_tables:
            table.to_metadata(metadata)
    return metadata


def prepare_schema(bind):
    """只接受空库或结构一致的本项目数据库，拒绝把旧库当作空库升级。"""
    if bind.dialect.name == "sqlite" and bind.url.database not in (None, "", ":memory:"):
        Path(bind.url.database).parent.mkdir(parents=True, exist_ok=True)
    metadata = current_metadata()
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())
    if not existing:
        metadata.create_all(bind)
        return
    incompatible = existing != set(metadata.tables)
    if not incompatible:
        for name, table in metadata.tables.items():
            columns = {column["name"] for column in inspector.get_columns(name)}
            primary_key = inspector.get_pk_constraint(name)["constrained_columns"]
            unique_sets = {tuple(value["column_names"]) for value in inspector.get_unique_constraints(name)}
            unique_sets.update(tuple(value["column_names"]) for value in inspector.get_indexes(name) if value["unique"])
            expected_unique = {tuple(column.name for column in constraint.columns)
                               for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}
            expected_unique.update(tuple(column.name for column in index.columns) for index in table.indexes if index.unique)
            if (columns != set(table.columns.keys()) or primary_key != [column.name for column in table.primary_key]
                    or not expected_unique.issubset(unique_sets)):
                incompatible = True
                break
    if incompatible:
        raise RuntimeError("数据库结构与当前项目不一致，已停止启动且未修改原数据。"
                           "本版本按首次运行准备，请将 DATABASE_URL 指向新的空数据库；不要删除旧库。")


def initialize_database(bind=engine, sessions=SessionLocal):
    prepare_schema(bind)
    with sessions() as db:
        admin_role = db.scalar(select(Role).where(Role.name == "admin"))
        if admin_role is None:
            admin_role = Role(name="admin", description="系统管理员",
                permissions_json=json.dumps(sorted(PERMISSIONS)), is_system=True)
            db.add(admin_role)
            db.flush()
        if db.scalar(select(Role.id).where(Role.name == "member")) is None:
            db.add(Role(name="member", description="门店会员", permissions_json="[]", is_system=True))
        # 仅创建缺少的初始管理员，重启不会改密码、余额或业务记录。
        if db.scalar(select(User.id).where(User.username == ADMIN_USERNAME)) is None:
            db.add(User(username=ADMIN_USERNAME, email=ADMIN_EMAIL.lower(),
                password_hash=hash_password(ADMIN_PASSWORD), name="管理员",
                role_id=admin_role.id, is_active=True))
        db.commit()


if __name__ == "__main__":
    initialize_database()
    print("数据库初始化完成，可以启动后端。")
