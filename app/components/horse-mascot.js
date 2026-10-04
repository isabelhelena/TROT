/** A little pony detective. Decorative, static, and independent of call logic. */
export default function HorseMascot({ className = '', attentive = false }) {
  return (
    <svg className={`horse-mascot ${className}`} viewBox="0 0 120 120" fill="none" aria-hidden="true" focusable="false">
      <circle cx="60" cy="60" r="55" fill="var(--mascot-paper, #f3e6d2)" />
      <circle cx="60" cy="60" r="49" stroke="#b19769" strokeOpacity=".5" strokeDasharray="2 5" />
      {/* Floppy mane, ears, and a rounded chestnut face. */}
      <path d="M33 49Q23 65 31 87L40 100H82L90 82Q96 57 82 45Z" fill="#6c4b39" />
      <path d="M37 42Q25 16 35 16 44 17 48 40M70 40Q75 16 85 16 95 17 83 44" fill="#c89c75" stroke="#684c39" strokeWidth="2.5" strokeLinejoin="round" />
      <path d="M35 24 39 37M83 24 78 37" stroke="#dfa5a0" strokeWidth="4" strokeLinecap="round" />
      <path d="M36 48Q60 31 84 48L85 76Q84 98 60 99 36 98 35 76Z" fill="#c89c75" stroke="#684c39" strokeWidth="2.5" />
      <path d="M54 48Q60 44 66 48L64 73H56Z" fill="#fff1d9" />
      <ellipse cx="60" cy="82" rx="24" ry="15" fill="#edd0b0" />
      <ellipse cx="42" cy="72" rx="6" ry="3.5" fill="#d99a91" fillOpacity=".7" />
      <ellipse cx="78" cy="72" rx="6" ry="3.5" fill="#d99a91" fillOpacity=".7" />
      {attentive ? <g fill="#392f29"><ellipse cx="46" cy="63" rx="3" ry="4" /><ellipse cx="74" cy="63" rx="3" ry="4" /><g fill="#fffaf1"><circle cx="47" cy="62" r="1" /><circle cx="75" cy="62" r="1" /></g></g> : <g stroke="#392f29" strokeWidth="2.5" strokeLinecap="round"><path d="M42 64Q46 60 50 64M70 64Q74 60 78 64" /></g>}
      <ellipse cx="51" cy="80" rx="2" ry="2.5" fill="#80563e" />
      <ellipse cx="69" cy="80" rx="2" ry="2.5" fill="#80563e" />
      <path d="M55 88Q60 92 65 88" stroke="#80563e" strokeWidth="2" strokeLinecap="round" />
      {/* Tweed detective cap with a bow and double brim. */}
      <path d="M32 46Q36 26 60 26 84 26 88 46Z" fill="#53694e" stroke="#294c3e" strokeWidth="2.5" />
      <path d="M46 29V45M60 27V45M74 29V45M37 36H83" stroke="#b7ad82" strokeWidth="1.3" strokeOpacity=".65" />
      <path d="M30 44Q60 40 90 44L94 50Q61 55 26 50Z" fill="#294c3e" />
      <path d="M55 27Q48 18 46 25 46 30 56 29M65 27Q72 18 74 25 74 30 64 29" fill="#aa784d" stroke="#76563e" strokeWidth="1.3" />
      <circle cx="60" cy="28" r="3" fill="#d6b77e" />
      {/* Little scarf and a magnifying glass tucked beside the pony. */}
      <path d="M41 94Q60 102 79 94L76 103Q60 110 44 103Z" fill="#a96855" />
      <path d="M61 104 68 114 78 109 70 102" fill="#a96855" />
      <path d="M47 99Q60 104 72 99" stroke="#ecc99c" strokeWidth="1.5" />
      <path d="M93 87 104 103" stroke="#795238" strokeWidth="5" strokeLinecap="round" />
      <circle cx="88" cy="79" r="12" fill="#f8f2de" fillOpacity=".8" stroke="#9a7844" strokeWidth="3" />
      <path d="M82 78Q82 73 88 73" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" />
      <path d="M18 56H24M21 53V59M97 32H103M100 29V35" stroke="#b19769" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
