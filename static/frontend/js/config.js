
const background = document.getElementById('background');
const emotionIndicator = document.getElementById('emotion-indicator');
const transcript = document.getElementById('transcript');
const micContainer = document.getElementById('mic-container');
const cardsContainer = document.getElementById('tool-cards-container');
const agentOutput = document.getElementById('agent-output');

const emotionEmojis = {
  neutral: '😐 中性',
  happy: '😊 開心',
  sad: '😢 悲傷',
  angry: '😡 生氣',
  fear: '😨 恐懼',
  surprise: '😲 驚訝'
};

const emotionColors = {
  neutral: 'linear-gradient(135deg, #E6F7F0 0%, #F5F1ED 100%)',
  happy: 'linear-gradient(135deg, #FFF9E6 0%, #FFE6E6 100%)',
  sad: 'linear-gradient(135deg, #E6F0FF 0%, #E6E6F5 100%)',
  angry: 'linear-gradient(135deg, #FFE6E6 0%, #F5E6E6 100%)',
  fear: 'linear-gradient(135deg, #F0E6FF 0%, #E6E6F5 100%)',
  surprise: 'linear-gradient(135deg, #FFFFE6 0%, #FFF5E6 100%)'
};

let typingInterval = null;

let ws = null;

let toolsMetadata = [];
