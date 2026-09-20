// Several photos of a lease, joined into one PDF before it is uploaded (docs/design/web.md §4,
// §8; ocr.md). The agreed POST /api/uploads has no way to group several files, and a lease is
// one document — so the joining happens here, in the browser, and the tenant's photos never
// leave the device except as that single PDF.
//
// A4 at 85% JPEG: enough for OCR to read a printed page, small enough to stay under 20 MB.
export const A4 = { width: 210, height: 297 }; // mm
export const QUALITY = 0.85;
export const MAX_PAGES = 30;

export type Drawn = { dataUrl: string; width: number; height: number };

/** Read one photo and re-encode it as a JPEG the PDF can hold. */
export async function drawn(file: File, canvas: HTMLCanvasElement): Promise<Drawn> {
  const image = await loadImage(file);
  canvas.width = image.width;
  canvas.height = image.height;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("This browser can't prepare photos for upload.");
  context.drawImage(image, 0, 0);
  return {
    dataUrl: canvas.toDataURL("image/jpeg", QUALITY),
    width: image.width,
    height: image.height,
  };
}

/** Each photo on its own A4 page, in the order the tenant chose them, scaled to fit.
 *
 * jsPDF is loaded here rather than imported at the top: it brings html2canvas and dompurify with
 * it, some 380 kB that a tenant uploading a PDF never needs. This is the one path that does. */
export async function pdfOf(pages: Drawn[]): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const pdf = new jsPDF({ unit: "mm", format: "a4" });
  pages.forEach((page, index) => {
    if (index > 0) pdf.addPage();
    const scale = Math.min(A4.width / page.width, A4.height / page.height);
    const width = page.width * scale;
    const height = page.height * scale;
    pdf.addImage(page.dataUrl, "JPEG", (A4.width - width) / 2, (A4.height - height) / 2, width, height);
  });
  return pdf.output("blob");
}

export async function joinPhotos(files: File[], canvas: HTMLCanvasElement): Promise<File> {
  if (files.length > MAX_PAGES) {
    throw new Error(`A lease may be at most ${MAX_PAGES} pages, and you chose ${files.length}.`);
  }
  const pages: Drawn[] = [];
  for (const file of files) pages.push(await drawn(file, canvas));
  return new File([await pdfOf(pages)], "lease.pdf", { type: "application/pdf" });
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((done, failed) => {
    const url = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      done(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      failed(new Error(`${file.name} couldn't be read as a photo.`));
    };
    image.src = url;
  });
}
