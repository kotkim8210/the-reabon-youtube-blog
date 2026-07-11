import { readBarcodes } from "zxing-wasm/reader";

// 택배 운송장(Code128/ITF 등) 프레임 디코딩. 유효한 첫 결과의 텍스트 반환.
export async function decodeFrame(imageData: ImageData): Promise<string | null> {
  try {
    const results = await readBarcodes(imageData, {
      formats: ["Code128", "Code39", "ITF", "EAN-13", "QRCode"],
      tryHarder: true,
    });
    const hit = results.find((r) => r.isValid && r.text.trim().length > 0);
    return hit ? hit.text.trim() : null;
  } catch {
    return null;
  }
}

export const digitsOnly = (s: string) => s.replace(/\D/g, "");
