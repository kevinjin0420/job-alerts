export interface ChartPalette {
  gridline: string;
  axis: string;
  baseline: string;
  /** 6 identity slots; a 7th (violet) failed the pie's wrap-around adjacency check in dark mode. */
  series: readonly string[];
  other: string;
}

const LIGHT: ChartPalette = {
  gridline: "#e1e0d9",
  axis: "#898781",
  baseline: "#c3c2b7",
  series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
  other: "#9a9890",
};

const DARK: ChartPalette = {
  gridline: "#2c2c2a",
  axis: "#898781",
  baseline: "#383835",
  series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"],
  other: "#6b6a64",
};

/** In TS not CSS vars: a canvas cannot resolve var(), so JS had to read them back anyway. */
export function chartPalette(isDark: boolean): ChartPalette {
  return isDark ? DARK : LIGHT;
}
