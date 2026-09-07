<template><router-view /></template>
<script>
export default { name: 'App' }
</script>
<style>
:root {
  font-family: Inter, 'Segoe UI', sans-serif;
  color: #13213c;
  background: #f4f7fb;
}
* {
  box-sizing: border-box;
}
body {
  margin: 0;
  background: #f4f7fb;
}
.auth {
  min-height: 100vh;
  display: grid;
  place-items: center;
  background: radial-gradient(circle at 15% 20%, #dcecff, transparent 35%),
    linear-gradient(145deg, #f8fbff, #edf2f9);
}
.auth-card {
  width: min(420px, calc(100vw - 32px));
  padding: 34px;
  border: 0;
  border-radius: 20px;
  box-shadow: 0 24px 70px rgba(31, 66, 120, 0.14);
}
.brand {
  font-size: 27px;
  font-weight: 800;
  color: #173f7a;
  margin-bottom: 7px;
}
.muted {
  color: #718096;
}
.wide {
  width: 100%;
}
.shell {
  min-height: 100vh;
}
.topbar {
  height: 68px;
  background: #123a70;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 28px;
}
.topbar h1 {
  font-size: 20px;
}
.layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  min-height: calc(100vh - 68px);
}
.nav {
  background: #fff;
  padding: 18px 10px;
  border-right: 1px solid #e7edf5;
}
.content {
  padding: 24px;
  max-width: 1400px;
  width: 100%;
}
.hero {
  background: linear-gradient(130deg, #184c91, #2d78c8);
  color: #fff;
  border-radius: 18px;
  padding: 28px;
  margin-bottom: 20px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
}
.panel {
  border: 0 !important;
  border-radius: 15px !important;
}
.metric {
  font-size: 30px;
  font-weight: 800;
  margin: 8px 0;
}
.toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 15px;
}
.mobile-nav {
  display: none;
}
@media (max-width: 760px) {
  .layout {
    display: block;
  }
  .nav {
    display: none;
  }
  .mobile-nav {
    display: flex;
    overflow: auto;
    background: #fff;
    padding: 8px;
  }
  .content {
    padding: 14px;
  }
  .topbar {
    padding: 0 16px;
  }
  .hero {
    padding: 20px;
  }
}
</style>
