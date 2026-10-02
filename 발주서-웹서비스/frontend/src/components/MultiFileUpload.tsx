import { useCallback, useRef, useState } from 'react';

// FileUpload와 같은 모양의 드롭존이지만 여러 파일을 받는다.
// 한 번에 여러 개 선택·드래그할 수 있고, 나중에 더 추가해도 기존 파일은 유지된다(같은 파일은 중복 제거).
interface MultiFileUploadProps {
  label: string;
  files: File[];
  onChange: (files: File[]) => void;
  accept?: string;
  acceptLabel?: string;
}

const sameFile = (a: File, b: File) => a.name === b.name && a.size === b.size;

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function MultiFileUpload({
  label,
  files,
  onChange,
  accept = '.xlsx,.xls',
  acceptLabel = '.xlsx, .xls 파일 · 여러 개 선택 가능',
}: MultiFileUploadProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const dragCounter = useRef(0);

  const addFiles = useCallback(
    (incoming: File[]) => {
      const next = [...files];
      for (const f of incoming) {
        if (!next.some((existing) => sameFile(existing, f))) next.push(f);
      }
      onChange(next);
    },
    [files, onChange],
  );

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
    dragCounter.current = 0;
    addFiles(Array.from(e.dataTransfer.files || []));
  };

  return (
    <div className="animate-fade-in">
      <label className="block text-sm font-semibold text-gray-700 mb-2">{label}</label>
      <div
        className={`drop-zone ${dragging ? 'dragging' : ''} ${files.length ? 'has-file' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(e) => { e.preventDefault(); e.stopPropagation(); dragCounter.current += 1; setDragging(true); }}
        onDragLeave={(e) => {
          e.preventDefault();
          e.stopPropagation();
          dragCounter.current -= 1;
          if (dragCounter.current === 0) setDragging(false);
        }}
        onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
        onDrop={handleDrop}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple
          onChange={(e) => {
            addFiles(Array.from(e.target.files || []));
            e.target.value = '';  // 같은 파일을 지웠다가 다시 고를 수 있게
          }}
          className="hidden"
        />

        {files.length > 0 ? (
          <div className="flex flex-col gap-3">
            {files.map((f, i) => (
              <div key={`${f.name}-${f.size}-${i}`} className="flex items-center gap-4">
                <div className="w-10 h-10 bg-indigo-100 rounded-xl flex items-center justify-center flex-shrink-0">
                  <svg className="w-5 h-5 text-indigo-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-900 truncate">{f.name}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{formatFileSize(f.size)}</p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onChange(files.filter((_, idx) => idx !== i));
                  }}
                  className="text-gray-400 hover:text-red-500 transition-colors p-1"
                  title="파일 제거"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
            <p className="text-xs text-indigo-600 font-semibold text-center">
              + 클릭하거나 드래그해서 파일 더 추가
            </p>
          </div>
        ) : (
          <div className="text-center">
            <svg className="mx-auto w-10 h-10 text-gray-400 mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
              />
            </svg>
            <p className="text-sm text-gray-600">
              <span className="text-indigo-600 font-semibold">클릭</span>
              하여 파일을 선택하거나 여기로{' '}
              <span className="text-indigo-600 font-semibold">드래그</span>
              하세요
            </p>
            <p className="text-xs text-gray-400 mt-1">{acceptLabel}</p>
          </div>
        )}
      </div>
    </div>
  );
}

export default MultiFileUpload;
