// CPU and memory from herald.stats() (the "stats" permission), every two seconds.
function show(id, percent) {
  const row = document.getElementById(id)
  row.querySelector('i').style.width = `${percent}%`
  row.querySelector('.value').textContent = `${Math.round(percent)}%`
  row.classList.toggle('high', percent >= 85)
}

async function tick() {
  try {
    const stats = await herald.stats()
    show('cpu', stats.cpuPercent)
    show('memory', (stats.memoryUsed / stats.memoryTotal) * 100)
  } catch (error) {
    document.body.textContent = error.message
  }
}

tick()
setInterval(tick, 2000)
