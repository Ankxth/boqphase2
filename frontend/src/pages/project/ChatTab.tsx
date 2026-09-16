import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, Bot, Send, Sparkles, User } from "lucide-react";
import { useRef, useState } from "react";
import { apiErrorMessage, askChat, listChatTools } from "../../lib/api";
import { fmtKg, fmtPct } from "../../lib/format";
import type { ChatAnswer } from "../../lib/types";
import { useCompany } from "../../lib/useCompany";
import { Badge } from "../../components/ui/Badge";
import { SpinnerInline } from "../../components/ui/Spinner";
import { useToast } from "../../components/ui/Toast";

interface Turn {
  id: number;
  question: string;
  answer?: ChatAnswer;
  pending?: boolean;
}

export default function ChatTab({ projectId }: { projectId: string }) {
  const { companyId } = useCompany();
  const toast = useToast();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const toolsQuery = useQuery({ queryKey: ["chat-tools"], queryFn: listChatTools });

  const mutation = useMutation({
    mutationFn: (question: string) => askChat(projectId, companyId, question),
  });

  const send = (question: string) => {
    if (!question.trim()) return;
    const id = Date.now();
    setTurns((t) => [...t, { id, question, pending: true }]);
    setInput("");
    mutation.mutate(question, {
      onSuccess: (answer) => {
        setTurns((t) => t.map((turn) => (turn.id === id ? { ...turn, answer, pending: false } : turn)));
        window.setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" }), 60);
      },
      onError: (err) => {
        toast.error(apiErrorMessage(err));
        setTurns((t) => t.filter((turn) => turn.id !== id));
      },
    });
  };

  const suggestions = toolsQuery.data
    ? Object.values(toolsQuery.data)
        .slice(0, 4)
        .map((t) => t.example_question)
    : [];

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <p className="text-[13px] text-ink-soft">
        Ask a what-if ("what if I use M40 instead of M30?") or a direct question ("how much carbon does steel
        contribute?"). Every answer is a real recomputed number, or an honest "I can't answer that yet."
      </p>

      {turns.length === 0 && suggestions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {suggestions.map((q, i) => (
            <button
              key={i}
              onClick={() => send(q)}
              className="neu-pill rounded-full border border-line bg-bg-raised px-3.5 py-2 text-left text-[12px] text-ink-soft transition-colors hover:border-coral/40 hover:text-ink"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      <div ref={scrollRef} className="flex max-h-[52vh] min-h-[220px] flex-col gap-4 overflow-y-auto rounded-2xl border border-line bg-bg-card/50 p-4">
        {turns.length === 0 && (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 py-10 text-center text-ink-faint">
            <Bot size={26} />
            <span className="text-[12.5px]">Ask about this project's carbon or cost</span>
          </div>
        )}
        {turns.map((turn) => (
          <div key={turn.id} className="flex flex-col gap-2">
            <div className="flex items-start justify-end gap-2">
              <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-coral px-3.5 py-2 text-[13px] text-bg">{turn.question}</div>
              <div className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-bg-raised text-ink-faint">
                <User size={12} />
              </div>
            </div>

            <div className="flex items-start gap-2">
              <div className="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-coral-soft text-coral">
                <Bot size={12} />
              </div>
              <div className="max-w-[85%] rounded-2xl rounded-tl-sm border border-line bg-bg-raised px-3.5 py-2.5 text-[13px] text-ink">
                {turn.pending ? (
                  <span className="flex items-center gap-2 text-ink-faint">
                    <SpinnerInline /> thinking…
                  </span>
                ) : turn.answer ? (
                  <AnswerBubble answer={turn.answer} />
                ) : null}
              </div>
            </div>
          </div>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="neu-inset flex items-center gap-2 rounded-full border border-line bg-bg-inset px-2 py-1.5"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about this project…"
          className="flex-1 bg-transparent px-3 py-2 text-[13.5px] text-ink outline-none placeholder:text-ink-faint"
        />
        <button
          type="submit"
          disabled={!input.trim() || mutation.isPending}
          className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-coral text-bg transition-transform disabled:opacity-40 enabled:hover:scale-105"
        >
          <Send size={15} />
        </button>
      </form>
    </div>
  );
}

function AnswerBubble({ answer }: { answer: ChatAnswer }) {
  return (
    <div>
      <p className="leading-relaxed">{answer.answer_text}</p>

      {!answer.applied && (
        <div className="mt-2 flex items-center gap-1.5 text-[11px] text-amber">
          <AlertCircle size={12} /> {answer.error?.replace(/_/g, " ") ?? "not applied"}
        </div>
      )}

      {answer.applied && answer.carbon_kg_before != null && answer.carbon_kg_after != null && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-2.5">
          {answer.current_value && answer.suggested_value && (
            <span className="flex items-center gap-1.5 font-mono text-[11px] text-ink-soft">
              {answer.current_value} <ArrowRight size={11} /> <span className="text-moss">{answer.suggested_value}</span>
            </span>
          )}
          <Badge tone="coral">{fmtKg(answer.carbon_kg_before)}</Badge>
          <ArrowRight size={11} className="text-ink-faint" />
          <Badge tone="moss">{fmtKg(answer.carbon_kg_after)}</Badge>
          {answer.savings_pct != null && <Badge tone="moss">−{fmtPct(answer.savings_pct)}</Badge>}
          {answer.requires_engineering_review && <Badge tone="amber">needs engineering review</Badge>}
        </div>
      )}

      {answer.data && Object.keys(answer.data).length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5 border-t border-line pt-2.5">
          {Object.entries(answer.data).map(([k, v]) => (
            <Badge key={k} tone="neutral" className="normal-case tracking-normal">
              {k.replace(/_/g, " ")}: {typeof v === "number" ? v.toLocaleString("en-IN", { maximumFractionDigits: 1 }) : String(v)}
            </Badge>
          ))}
        </div>
      )}

      <div className="mt-2 flex items-center gap-1.5 text-[10px] text-ink-faint">
        <Sparkles size={10} />
        {answer.tool_call.tool ? answer.tool_call.tool.replace(/_/g, " ") : "unparsed"} · {answer.tool_call.parse_source.replace("_", " ")}
      </div>
    </div>
  );
}
