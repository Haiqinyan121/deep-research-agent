/** 展示层的小格式化函数。 */

/** 毫秒 → `1:05` / `12.3s`（一分钟以内给一位小数，更符合「秒表」直觉）。 */
export function formatDuration(ms: number): string {
  if (ms <= 0) return "0.0s";
  const totalSeconds = ms / 1000;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.floor(totalSeconds % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** 时间戳 → `14:03:27`，事件日志用。 */
export function formatClock(at: number): string {
  const date = new Date(at);
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
}

/** 粗略估算字数：中文按字算，英文按词算，够报告页脚用了。 */
export function countWords(text: string): number {
  if (!text) return 0;
  const cjk = (text.match(/[一-龥]/g) || []).length;
  const latin = (text.match(/[A-Za-z0-9]+/g) || []).length;
  return cjk + latin;
}

/** 把主题变成安全的文件名。 */
export function toFileName(topic: string): string {
  const base = topic.trim().replace(/[\\/:*?"<>|\s]+/g, "-").slice(0, 40) || "research";
  const stamp = new Date().toISOString().slice(0, 10);
  return `${base}-${stamp}.md`;
}
