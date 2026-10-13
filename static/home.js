// Home page: year -> Grand Prix dropdowns, then jump to the results page.
const form = document.getElementById('home-form');
const year = document.getElementById('year');
const meeting = document.getElementById('meeting');
const spinner = document.getElementById('meetings-spinner');
const meetingsError = document.getElementById('meetings-error');
const submitError = document.getElementById('submit-error');
const submit = document.getElementById('submit');
const submitLabel = submit.textContent;

let loading = false;
let submitting = false;
let latest = 0; // ignore responses from a year that is no longer selected

function update() {
  submit.disabled = !(year.value && meeting.value && !loading && !submitting);
}

function setPlaceholder(text) {
  meeting.options[0].textContent = text;
}

async function loadMeetings() {
  const request = ++latest;
  meeting.length = 1;
  meeting.value = '';
  meeting.disabled = true;
  meetingsError.hidden = true;
  spinner.hidden = false;
  setPlaceholder('Loading…');
  loading = true;
  update();

  try {
    const res = await fetch(`/api/meetings?year=${encodeURIComponent(year.value)}`);
    const data = await res.json();
    if (request !== latest) return;
    if (!res.ok) throw new Error(data.error || 'Failed to load.');
    for (const m of data) {
      const option = new Option(m.meeting_name, m.meeting_key);
      option.className = 'bg-[#1C2330]';
      meeting.add(option);
    }
    setPlaceholder('Select Grand Prix');
    meeting.disabled = false;
  } catch (e) {
    if (request !== latest) return;
    meetingsError.querySelector('span').textContent = e.message;
    meetingsError.hidden = false;
    setPlaceholder('Failed to load');
  } finally {
    if (request === latest) {
      loading = false;
      spinner.hidden = true;
      update();
    }
  }
}

year.addEventListener('change', loadMeetings);
meeting.addEventListener('change', update);
meetingsError.querySelector('button').addEventListener('click', loadMeetings);

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (submit.disabled) return;
  submitError.hidden = true;
  submitting = true;
  submit.disabled = true;
  submit.innerHTML = spinnerSvg(16) + 'Loading…';

  try {
    const res = await fetch(`/api/race-session/${encodeURIComponent(meeting.value)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Failed to load session.');
    location.href = `/results/${encodeURIComponent(meeting.value)}`;
  } catch (err) {
    submitError.textContent = err.message;
    submitError.hidden = false;
    submitting = false;
    submit.textContent = submitLabel;
    update();
  }
});

if (year.value) loadMeetings(); // browser restored a previous selection
