/** 图片压缩：持仓截图上传前缩放 + JPEG 压缩，控制在后端/Vercel 请求体限制内。 */

const MAX_EDGE = 1600; // 最长边
const TARGET_QUALITIES = [0.85, 0.7, 0.55, 0.4];

export async function compressImage(file: File | Blob, maxBytes = 1_200_000): Promise<string> {
  const bitmap = await loadBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(1, Math.round(bitmap.width * scale));
  const h = Math.max(1, Math.round(bitmap.height * scale));

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("浏览器不支持 Canvas，无法处理截图");
  ctx.drawImage(bitmap, 0, 0, w, h);
  if ("close" in bitmap && typeof bitmap.close === "function") bitmap.close();

  let dataUrl = canvas.toDataURL("image/jpeg", TARGET_QUALITIES[0]);
  // 逐级降质量直到满足体积
  for (const q of TARGET_QUALITIES.slice(1)) {
    if (dataUrl.length <= maxBytes) break;
    dataUrl = canvas.toDataURL("image/jpeg", q);
  }
  if (dataUrl.length > maxBytes) {
    throw new Error("截图过大，请截取持仓区域后重试");
  }
  return dataUrl;
}

async function loadBitmap(file: File | Blob): Promise<ImageBitmap | HTMLImageElement> {
  if ("createImageBitmap" in window) {
    try {
      return await createImageBitmap(file);
    } catch {
      /* fallthrough */
    }
  }
  const url = URL.createObjectURL(file);
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => reject(new Error("图片读取失败"));
      img.src = url;
    });
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
}
