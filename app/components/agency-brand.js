import HorseMascot from './horse-mascot';

export default function AgencyBrand({ subtitle }) {
  return (
    <div className="brand agency-brand">
      <HorseMascot />
      <div className="brand-copy">TROT<span>{subtitle}</span></div>
    </div>
  );
}
