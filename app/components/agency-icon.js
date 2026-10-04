/** Small ink-style clues. Labels stay in plain language beside each icon. */
export default function AgencyIcon({ kind = 'lens' }) {
  return <svg className="agency-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
    {kind === 'notebook' ? <><rect x="5" y="3" width="15" height="18" rx="2" /><path d="M9 3V21M3 7H6M3 12H6M3 17H6M12 8H17M12 12H17M12 16H15" /></> : kind === 'horseshoe' ? <><path d="M6 4C2 10 3 20 12 20S22 10 18 4L14 6C17 11 17 16 12 16S7 11 10 6Z" /><path d="M6 10H7M6 14H7M17 10H18M17 14H18M10 18H10.5M13.5 18H14" /></> : <><circle cx="10" cy="10" r="6" /><path d="M14.5 14.5 21 21M7 9Q7 7 10 7" /></>}
  </svg>;
}
