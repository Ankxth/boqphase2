import { useMutation } from "@tanstack/react-query";
import { UploadCloud } from "lucide-react";
import { useState } from "react";
import { apiErrorMessage, refineWithOwnBoq } from "../../lib/api";
import type { ProjectSchema, RefineResponse } from "../../lib/types";
import { useCompany } from "../../lib/useCompany";
import { Button } from "../../components/ui/Button";
import { Card, CardLabel } from "../../components/ui/Card";
import { Dropzone } from "../../components/ui/Dropzone";
import { useToast } from "../../components/ui/Toast";

export default function RefineTab({ project }: { project: ProjectSchema }) {
  const { companyId } = useCompany();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<RefineResponse | null>(null);

  const mutation = useMutation({
    mutationFn: () => refineWithOwnBoq(project.project_id, companyId, file!),
    onSuccess: (data) => {
      setResult(data);
      toast.success("Refined against your own BOQ.");
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-5">
      <p className="text-[13px] text-ink-soft">
        Have an actual Bill of Quantities for this project? Upload it to refine the concept-stage estimate against real
        quantities, instead of Phase 1's typical-ratio assumptions.
      </p>

      <Card>
        <CardLabel>Bill of Quantities (.xlsx / .xls)</CardLabel>
        <Dropzone file={file} onFile={setFile} accept=".xlsx,.xls" hint="Same shape as any BOQ Excel file" />
        <div className="mt-4 flex justify-end">
          <Button onClick={() => mutation.mutate()} disabled={!file} loading={mutation.isPending} icon={<UploadCloud size={15} />}>
            Refine estimate
          </Button>
        </div>
      </Card>

      {result && (
        <Card accent="moss">
          <CardLabel>Refined result</CardLabel>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all font-mono text-[11.5px] leading-relaxed text-ink-soft">
            {JSON.stringify(result, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
