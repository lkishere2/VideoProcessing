function formatTime(seconds) {
  const m = Math.floor(seconds / 60).toString().padStart(2, '0');
  const s = (Math.floor(seconds % 60)).toString().padStart(2, '0');
  return `${m}:${s}`;
}

const EMOTION_COLORS = {
  Excited: '#fca5a5',
  Sad: '#93c5fd',
  Neutral: '#9ca3af',
};

function EmotionBadge({ emotion }) {
  const color = EMOTION_COLORS[emotion] || EMOTION_COLORS.Neutral;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '999px',
        fontSize: '0.7rem',
        fontWeight: 600,
        letterSpacing: '0.02em',
        color: color,
        border: `1px solid ${color}`,
        background: 'rgba(255,255,255,0.04)',
      }}
    >
      {emotion || 'Neutral'}
    </span>
  );
}

export default function AudioSection({ voiceSegments }) {
  if (!voiceSegments || voiceSegments.length === 0) return null;

  const sorted = [...voiceSegments].sort((a, b) => a.start - b.start);

  return (
    <div className="glass-panel" style={{ marginTop: '20px' }}>
      <div style={{ marginBottom: '20px' }}>
        <h3 style={{ margin: 0, color: 'var(--text-main)', fontSize: '1.25rem', fontWeight: '600' }}>
          🔊 Audio & Transcription Chunks ({sorted.length})
        </h3>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: '4px' }}>
          Significant sound events transcribed locally and tagged with emotion.
        </p>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {sorted.map((seg, i) => (
          <div
            key={i}
            style={{
              textAlign: 'left',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              padding: '16px',
              background: 'rgba(255, 255, 255, 0.02)',
              border: '1px solid rgba(255, 255, 255, 0.05)',
              borderRadius: '12px',
              transition: 'background 0.2s ease, border-color 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)';
              e.currentTarget.style.borderColor = 'rgba(139, 92, 246, 0.2)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)';
              e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.05)';
            }}
          >
            {/* Header row: time + emotion + download */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--primary)', fontFamily: 'monospace', fontWeight: '600' }}>
                  ⏱️ {formatTime(seg.start)} – {formatTime(seg.end)}
                </span>
                <EmotionBadge emotion={seg.emotion} />
              </div>
              
              {seg.audio_b64 && (
                <a 
                  href={seg.audio_b64} 
                  download={`chunk_${i}.wav`} 
                  style={{ 
                    fontSize: '0.75rem', 
                    color: 'var(--text-main)', 
                    textDecoration: 'none',
                    padding: '4px 10px',
                    borderRadius: '6px',
                    background: 'rgba(255,255,255,0.06)',
                    border: '1px solid rgba(255,255,255,0.08)',
                    transition: 'background 0.2s'
                  }}
                  onMouseEnter={(e) => e.target.style.background = 'rgba(255,255,255,0.12)'}
                  onMouseLeave={(e) => e.target.style.background = 'rgba(255,255,255,0.06)'}
                >
                  📥 Download WAV
                </a>
              )}
            </div>

            {/* Transcription text */}
            <div style={{ fontSize: '0.95rem', color: 'var(--text-main)', lineHeight: '1.5', paddingLeft: '4px' }}>
              {seg.text ? (
                <span>🎙️ "{seg.text}"</span>
              ) : (
                <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>(No speech detected in this segment)</span>
              )}
            </div>

            {/* Audio player */}
            {seg.audio_b64 && (
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <audio 
                  controls 
                  src={seg.audio_b64} 
                  style={{ 
                    width: '100%', 
                    maxWidth: '450px', 
                    height: '32px',
                    filter: 'invert(0.9) hue-rotate(180deg) opacity(0.85)'
                  }} 
                />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}