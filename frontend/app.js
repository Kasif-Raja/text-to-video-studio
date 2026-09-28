const scriptInput = document.getElementById('scriptInput');
const voiceSelect = document.getElementById('voiceSelect');
const maxSecondsInput = document.getElementById('maxSeconds');
const generateBtn = document.getElementById('generateBtn');
const splitBtn = document.getElementById('splitBtn');
const statusBox = document.getElementById('statusBox');
const progressBar = document.getElementById('progressBar');
const sceneList = document.getElementById('sceneList');
const downloadRow = document.getElementById('downloadRow');
const downloadLink = document.getElementById('downloadLink');

let currentJobId = null;

function showStatus(message, isError = false) {
  statusBox.textContent = message;
  statusBox.classList.add('visible');
  statusBox.style.borderColor = isError ? 'rgba(255,123,123,0.35)' : 'rgba(101,214,255,0.2)';
  statusBox.style.background = isError ? 'rgba(255,123,123,0.08)' : 'rgba(101,214,255,0.06)';
}

function setProgress(value) {
  progressBar.style.width = `${Math.max(0, Math.min(100, value))}%`;
}

function buildSceneCards(scenes) {
  sceneList.innerHTML = '';

  scenes.forEach((scene, index) => {
    const card = document.createElement('div');
    card.className = 'scene-item';

    const header = document.createElement('div');
    header.className = 'scene-header';
    header.innerHTML = `<span class="scene-number">Scene ${index + 1}</span>`;

    const textArea = document.createElement('textarea');
    textArea.value = scene.text || '';

    const keywordInput = document.createElement('input');
    keywordInput.type = 'text';
    keywordInput.value = scene.keyword || '';
    keywordInput.placeholder = 'Visual keyword';

    card.appendChild(header);
    card.appendChild(textArea);
    card.appendChild(keywordInput);
    sceneList.appendChild(card);
  });
}

function parseScenesFromScript() {
  const script = scriptInput.value.trim();
  if (!script) {
    showStatus('Please enter a script before splitting scenes.', true);
    return [];
  }

  const sentences = script
    .split(/(?<=[.!?])\s+|\n+/)
    .map((item) => item.trim())
    .filter(Boolean);

  const windows = [];
  let current = '';

  for (const sentence of sentences) {
    const candidate = current ? `${current} ${sentence}` : sentence;
    if (candidate.length <= 420) {
      current = candidate;
    } else {
      if (current) windows.push(current);
      current = sentence;
    }
  }
  if (current) windows.push(current);

  const scenes = windows.map((text) => ({
    text,
    keyword: text.split(/\s+/).slice(0, 6).join(' '),
  }));

  if (!scenes.length) {
    return [{ text: script, keyword: script.split(/\s+/).slice(0, 6).join(' ') }];
  }

  return scenes;
}

splitBtn.addEventListener('click', () => {
  const scenes = parseScenesFromScript();
  buildSceneCards(scenes);
});

generateBtn.addEventListener('click', async () => {
  const script = scriptInput.value.trim();
  if (!script) {
    showStatus('Please provide script content to generate a video.', true);
    return;
  }

  const scenes = Array.from(sceneList.children)
    .map((item) => {
      const textArea = item.querySelector('textarea');
      const keywordInput = item.querySelector('input');
      return {
        text: textArea.value.trim(),
        keyword: keywordInput.value.trim(),
      };
    })
    .filter((scene) => scene.text);

  if (!scenes.length) {
    showStatus('At least one scene is required before rendering.', true);
    return;
  }

  showStatus('Submitting video job...');
  setProgress(5);
  generateBtn.disabled = true;
  downloadRow.classList.remove('visible');

  const body = {
    script,
    voice: voiceSelect.value,
    max_duration_seconds: Number(maxSecondsInput.value || 600),
    scenes,
  };

  try {
    const response = await fetch('/api/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || 'Failed to start the render job.');
    }

    const result = await response.json();
    currentJobId = result.job_id;
    pollJobStatus(currentJobId);
  } catch (err) {
    showStatus(err.message || 'Could not submit the render job.', true);
    generateBtn.disabled = false;
  }
});

async function pollJobStatus(jobId) {
  try {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (!response.ok) {
      throw new Error('Could not fetch the job status.');
    }

    const data = await response.json();
    setProgress(data.progress || 0);

    if (data.status === 'queued' || data.status === 'processing') {
      showStatus(`Generating video... ${data.progress}%`);
      setTimeout(() => pollJobStatus(jobId), 1800);
      return;
    }

    if (data.status === 'completed') {
      showStatus('Video finished successfully.');
      setProgress(100);
      downloadRow.classList.add('visible');
      downloadLink.href = data.download_url || `/api/download/${jobId}`;
      downloadLink.download = `${jobId}.mp4`;
      generateBtn.disabled = false;
      return;
    }

    if (data.status === 'failed') {
      showStatus(data.error || 'The video generation failed.', true);
      generateBtn.disabled = false;
      return;
    }
  } catch (err) {
    showStatus(err.message || 'Status polling failed.', true);
    generateBtn.disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  const initialScenes = parseScenesFromScript();
  buildSceneCards(initialScenes);
});
