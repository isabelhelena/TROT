'use client';
import { useEffect, useRef } from 'react';

/** Native disclosure keeps keyboard access and manual closing built in. */
export default function CaseFolder({ title, tab, description, attentionKey, urgent = false, onOpen, className = '', children }) {
  const folder = useRef(null);
  const lastAttention = useRef(null);
  useEffect(() => {
    if (attentionKey && attentionKey !== lastAttention.current) {
      folder.current.open = true;
      lastAttention.current = attentionKey;
    }
  }, [attentionKey]);

  return <details ref={folder} className={`card case-folder ${urgent ? 'folder-urgent' : ''} ${className}`} onToggle={(event) => {
    if (event.currentTarget.open) onOpen?.();
  }}>
    <summary className="folder-cover">
      <span className="folder-tab">{tab}</span>
      <svg className="folder-icon" viewBox="0 0 32 28" fill="none" aria-hidden="true" focusable="false">
        <path d="M3 23V6a2 2 0 0 1 2-2h7l3 4h12a2 2 0 0 1 2 2v13Z" fill="#d8be92" stroke="currentColor" strokeWidth="1.5" />
        <path className="folder-front" d="M3 12h26v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" fill="#efdec0" stroke="currentColor" strokeWidth="1.5" />
      </svg>
      <div className="folder-title"><h2>{title}</h2><span className="folder-description">{description}</span>{urgent && <span className="folder-warning">Possible scam · review transcript</span>}</div>
      <span className="folder-disclosure" aria-hidden="true"><span className="folder-open-label">Open</span><span className="folder-close-label">Close</span><span className="folder-chevron">⌄</span></span>
    </summary>
    <div className="folder-contents">{children}</div>
  </details>;
}
