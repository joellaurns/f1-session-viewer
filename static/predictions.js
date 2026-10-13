// Show the team colour and name under each podium dropdown.
const drivers = JSON.parse(document.getElementById('drivers').textContent);

document.querySelectorAll('#podium > div').forEach((field) => {
  const select = field.querySelector('select');
  const hint = field.querySelector('[data-hint]');
  if (!select || !hint) return;

  function update() {
    const driver = drivers.find((d) => d.name === select.value);
    hint.hidden = !driver;
    if (!driver) return;
    hint.children[0].style.background = driver.colour;
    hint.children[1].textContent = driver.team;
  }

  select.addEventListener('change', update);
  update();
});
