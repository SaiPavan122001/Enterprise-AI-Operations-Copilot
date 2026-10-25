/** Small inline SVG icons (currentColor, 20px by default). */

function Svg({ size = 20, children, ...rest }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...rest}>
      {children}
    </svg>
  );
}

export const PanelIcon = (p) => (
  <Svg {...p}><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M9 4v16" /></Svg>
);
export const PenIcon = (p) => (
  <Svg {...p}><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></Svg>
);
export const SunIcon = (p) => (
  <Svg {...p}><circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Svg>
);
export const MoonIcon = (p) => (
  <Svg {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" /></Svg>
);
export const ArrowUpIcon = (p) => (
  <Svg {...p} strokeWidth="2.2"><path d="M12 19V5M5 12l7-7 7 7" /></Svg>
);
export const ChevronIcon = (p) => (
  <Svg {...p}><path d="m9 6 6 6-6 6" /></Svg>
);
export const CopyIcon = (p) => (
  <Svg {...p}><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h10" /></Svg>
);
export const CheckIcon = (p) => (
  <Svg {...p}><path d="M20 6 9 17l-5-5" /></Svg>
);
export const ThumbUpIcon = (p) => (
  <Svg {...p}><path d="M7 10v11H4a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1Z" />
    <path d="M7 10 11 3a2 2 0 0 1 3 2l-1 5h6a2 2 0 0 1 2 2.3l-1.4 7A2 2 0 0 1 17.6 21H7" /></Svg>
);
export const ThumbDownIcon = (p) => (
  <Svg {...p}><path d="M17 14V3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1Z" />
    <path d="m17 14-4 7a2 2 0 0 1-3-2l1-5H5a2 2 0 0 1-2-2.3l1.4-7A2 2 0 0 1 6.4 3H17" /></Svg>
);
export const ToolIcon = (p) => (
  <Svg {...p}><path d="M14.7 6.3a4 4 0 0 0-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 0 0 5.2-5.4l-2.6 2.6-2.4-.6-.6-2.4Z" /></Svg>
);
export const LogoutIcon = (p) => (
  <Svg {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><path d="m16 17 5-5-5-5M21 12H9" /></Svg>
);
export const CloseIcon = (p) => (
  <Svg {...p}><path d="M18 6 6 18M6 6l12 12" /></Svg>
);
export const SparkIcon = (p) => (
  <Svg {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M6.3 17.7l2.5-2.5M15.2 8.8l2.5-2.5" /></Svg>
);
