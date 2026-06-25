function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (Math.floor(seconds % 60)).toString().padStart(2, '0');
  return `${m}:${s}`;
}

export default function ImageItem({ frameData, index, onClick }) {
  const handleOpen = () => onClick(index);

  return (
    <button type="button" className="frame-item clickable" onClick={handleOpen}>
      <div className="frame-image-wrap">
        <img src={frameData.base64} alt={`Frame ${index + 1}`} loading="lazy" />
        <div className="frame-overlay">View full size</div>
      </div>
      <div className="frame-timestamp">
        {formatTime(frameData.t1)}
        {frameData.execution_time > 0 && (
          <span style={{color: '#aaa', marginLeft: '5px'}}>(took {frameData.execution_time.toFixed(2)}s)</span>
        )}
      </div>
    </button>
  );
}
