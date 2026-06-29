function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (Math.floor(seconds % 60)).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export default function ImageItem({ frameData, index, onClick }) {
  const handleOpen = () => onClick(index);

  const handlePlayAudio = (e) => {
    e.stopPropagation(); // Prevent opening the full-size modal
    if (frameData.audio) {
      const sound = new Audio(frameData.audio);
      sound.play();
    }
  };

  return (
    <div className="frame-item clickable" onClick={handleOpen} style={{ cursor: 'pointer' }}>
      <div className="frame-image-wrap">
        <img src={frameData.base64} alt={`Frame ${index + 1}`} loading="lazy" />
        <div className="frame-overlay">View full size</div>
      </div>
      <div className="frame-timestamp" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
        <span>{formatTime(frameData.t1)} - {formatTime(frameData.t2)}</span>
        {frameData.audio && (
          <button 
            type="button" 
            onClick={handlePlayAudio}
            style={{
              background: 'rgba(139, 92, 246, 0.15)',
              border: '1px solid rgba(139, 92, 246, 0.3)',
              borderRadius: '50%',
              width: '24px',
              height: '24px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              color: 'var(--primary)',
              padding: 0
            }}
            title="Play frame audio"
          >
            ▶️
          </button>
        )}
      </div>
      {frameData.voice_text && (
        <div style={{padding: '8px', fontSize: '0.75rem', color: '#888', borderTop: '1px solid rgba(255,255,255,0.1)', textAlign: 'left', wordBreak: 'break-word'}}>
          🎙️ {frameData.voice_text}
        </div>
      )}
    </div>
  );
}
