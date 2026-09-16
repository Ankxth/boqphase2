import { FileSpreadsheet, FileText, UploadCloud, X } from "lucide-react";
import { useCallback, useRef, useState, type DragEvent } from "react";
import clsx from "clsx";

export function Dropzone({
  file,
  onFile,
  accept,
  label,
  hint,
}: {
  file: File | null;
  onFile: (f: File | null) => void;
  accept: string;
  label?: string;
  hint?: string;
}) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      const f = e.dataTransfer.files?.[0];
      if (f) onFile(f);
    },
    [onFile]
  );

  const isPdf = file?.name.toLowerCase().endsWith(".pdf");

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={clsx(
          "neu-inset flex cursor-pointer flex-col items-center justify-center gap-2.5 rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragging ? "border-coral bg-coral-soft" : "border-line hover:border-line-strong"
        )}
      >
        {file ? (
          <>
            <div className="flex items-center gap-2 text-moss">
              {isPdf ? <FileText size={22} /> : <FileSpreadsheet size={22} />}
            </div>
            <div className="max-w-full truncate px-4 text-[13px] font-medium text-ink">{file.name}</div>
            <div className="text-[11px] text-ink-faint">{(file.size / 1024).toFixed(0)} KB · click to replace</div>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onFile(null);
                if (inputRef.current) inputRef.current.value = "";
              }}
              className="mt-1 inline-flex items-center gap-1 text-[11px] text-ink-faint hover:text-rust"
            >
              <X size={12} /> remove
            </button>
          </>
        ) : (
          <>
            <UploadCloud size={26} className="text-ink-faint" />
            <div className="text-[13.5px] text-ink-soft">{label ?? "Drop a file, or click to browse"}</div>
            {hint && <div className="text-[11px] text-ink-faint">{hint}</div>}
          </>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => onFile(e.target.files?.[0] ?? null)}
      />
    </div>
  );
}
