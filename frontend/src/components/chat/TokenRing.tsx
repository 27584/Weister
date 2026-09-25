"use client";

/** 简单 SVG 圆环进度指示器。 */
export function TokenRing({ pct }: { pct: number }) {
  const radius = 8;
  const stroke = 2;
  const normalizedRadius = radius - stroke / 2;
  const circumference = normalizedRadius * 2 * Math.PI;
  const dash = Math.min(1, Math.max(0, pct)) * circumference;

  let color = "text-success";
  if (pct > 0.8) color = "text-error";
  else if (pct > 0.5) color = "text-warning";

  return (
    <svg
      width={radius * 2}
      height={radius * 2}
      className={`${color} shrink-0 rotate-[-90deg]`}
      aria-hidden="true"
    >
      <circle
        stroke="currentColor"
        fill="transparent"
        strokeWidth={stroke}
        r={normalizedRadius}
        cx={radius}
        cy={radius}
        className="opacity-20"
      />
      <circle
        stroke="currentColor"
        fill="transparent"
        strokeWidth={stroke}
        strokeLinecap="round"
        r={normalizedRadius}
        cx={radius}
        cy={radius}
        strokeDasharray={`${dash} ${circumference - dash}`}
      />
    </svg>
  );
}
