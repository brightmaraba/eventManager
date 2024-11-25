document.addEventListener('DOMContentLoaded', function () {
  const dateElement = document.getElementById('date')
  const currentDate = new Date().toISOString().split('T')[0]
  dateElement.textContent = currentDate
})
