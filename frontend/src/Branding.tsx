import logoUrl from "../Logo02.png";

export const YEDF_BRAND = {
  productName: "YEDF SPACE",
  institutionName: "Youth Enterprise Development Fund",
  productDescription: "Institutional Meeting and Event Management System",
  institutionDescription: "A state corporation mandated to provide financial and business development support services to youth-owned enterprises.",
  logoUrl,
};

export function BrandLockup({ className = "yedf-brand-lockup" }: { className?: string }) {
  return <span className={`yedf-brand ${className}`}>
    <img src={YEDF_BRAND.logoUrl} alt="" aria-hidden="true" />
    <span>{YEDF_BRAND.productName}</span>
  </span>;
}

export function InstitutionalFooter({ className = "footer" }: { className?: string }) {
  return <footer className={`yedf-page-footer ${className}`}>
    <img src={YEDF_BRAND.logoUrl} alt="Youth Enterprise Development Fund logo" />
    <span>
      <strong>{YEDF_BRAND.institutionName}</strong>
      <small>{YEDF_BRAND.productDescription}</small>
      <small>{YEDF_BRAND.institutionDescription}</small>
    </span>
  </footer>;
}
