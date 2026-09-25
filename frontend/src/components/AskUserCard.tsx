"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckSquare,
  HelpCircle,
  Send,
  SkipForward,
  Square,
} from "lucide-react";
import type { AskAnswer, PendingAsk } from "@/lib/types";

/** 后端固定追加的自填选项标签，命中时需要展开输入框 */
export const OTHER_LABEL = "其他（自行输入）";

interface Props {
  ask: PendingAsk;
  onSubmit: (answers: AskAnswer[]) => void;
  onSkip: () => void;
}

/**
 * 智能体提问卡片。
 *
 * 一次询问可能包含多道问题，逐道展示并标注进度（第 1/4 问）；
 * 单选题选中即自动进入下一问，多选题需显式点「下一问」；
 * 选中「其他（自行输入）」时展开文本框，其内容与选项一并回传。
 */
export function AskUserCard({ ask, onSubmit, onSkip }: Props) {
  const total = ask.questions.length;
  const advanceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<AskAnswer[]>(() =>
    ask.questions.map(() => ({ selected: [], other: "" })),
  );

  // 换了一轮询问（qid 变化）后重置作答状态，避免带着上一轮的选择
  useEffect(() => {
    setIndex(0);
    setAnswers(ask.questions.map(() => ({ selected: [], other: "" })));
  }, [ask.qid, ask.questions]);

  const current = ask.questions[index];
  const currentAnswer = answers[index] ?? { selected: [], other: "" };
  const otherActive = currentAnswer.selected.includes(OTHER_LABEL);
  const isLast = index === total - 1;

  const canAdvance = useMemo(() => {
    if (currentAnswer.selected.length === 0) return false;
    // 选了「其他」就必须填写内容，否则回传一个空的自填项没有意义
    if (otherActive && !currentAnswer.other.trim()) return false;
    return true;
  }, [currentAnswer, otherActive]);

  const patch = (next: Partial<AskAnswer>) => {
    setAnswers((prev) => {
      const copy = prev.slice();
      copy[index] = { ...(copy[index] ?? { selected: [], other: "" }), ...next };
      return copy;
    });
  };

  const toggle = (label: string) => {
    if (!current) return;
    if (current.multiSelect) {
      const has = currentAnswer.selected.includes(label);
      patch({
        selected: has
          ? currentAnswer.selected.filter((s) => s !== label)
          : [...currentAnswer.selected, label],
        other: label === OTHER_LABEL && has ? "" : currentAnswer.other,
      });
      return;
    }

    // 单选：直接替换。切走「其他」时清掉已填文本，避免残留无效内容
    patch({
      selected: [label],
      other: label === OTHER_LABEL ? currentAnswer.other : "",
    });
    // 单选且不是自填项时自动进入下一问，省一次点击。
    // 放在这里而不是用 effect 监听选择变化：否则用户返回上一问修改答案时，
    // 监听会立刻又把他推到下一问，导致无法回头改。
    if (label !== OTHER_LABEL) {
      clearTimeout(advanceTimer.current);
      advanceTimer.current = setTimeout(() => {
        setIndex((i) => Math.min(i + 1, total - 1));
      }, 200);
    }
  };

  useEffect(() => () => clearTimeout(advanceTimer.current), []);

  if (!current) return null;

  const go = (delta: number) =>
    setIndex((i) => Math.min(Math.max(i + delta, 0), total - 1));

  return (
    <div className="rounded-[var(--radius-box)] border border-primary/35 bg-primary/[0.04] p-3">
      <div className="mb-2.5 flex items-start gap-2">
        <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <p className="text-[14px] font-semibold text-base-content">
            {ask.title}
          </p>
          <p className="mt-0.5 text-[14px] text-base-content/90">
            第 {index + 1} / {total} 问 · {current.multiSelect ? "可多选" : "单选"}
          </p>
        </div>
        <button
          onClick={onSkip}
          className="btn btn-xs shrink-0 gap-1 border-base-300 bg-base-100 text-base-content/90"
          title="不作答，由智能体自行采用默认口径"
        >
          <SkipForward className="h-3 w-3" />
          跳过
        </button>
      </div>

      <p className="mb-2 text-[14px] font-medium leading-relaxed text-base-content">
        {current.question}
      </p>

      <div className="flex flex-col gap-1.5">
        {current.options.map((opt) => {
          const active = currentAnswer.selected.includes(opt.label);
          const Icon = current.multiSelect ? (
            active ? (
              <CheckSquare className="h-3.5 w-3.5 text-primary" />
            ) : (
              <Square className="h-3.5 w-3.5 text-base-content/70" />
            )
          ) : active ? (
            <Check className="h-3.5 w-3.5 text-primary" />
          ) : (
            <span className="h-3.5 w-3.5 shrink-0 rounded-full border border-base-content/40" />
          );
          return (
            <button
              key={opt.label}
              type="button"
              onClick={() => toggle(opt.label)}
              aria-pressed={active}
              className={`flex items-start gap-2 rounded-[var(--radius-field)] border px-2.5 py-2 text-left transition-colors ${
                active
                  ? "border-primary/50 bg-primary/[0.08]"
                  : "border-base-300 bg-base-100 hover:border-base-content/35"
              }`}
            >
              <span className="mt-0.5 shrink-0">{Icon}</span>
              <span className="min-w-0">
                <span className="block text-[14px] font-medium text-base-content">
                  {opt.label}
                </span>
                {opt.description && (
                  <span className="mt-0.5 block text-[14px] leading-snug text-base-content/90">
                    {opt.description}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      {otherActive && (
        <textarea
          autoFocus
          value={currentAnswer.other}
          onChange={(e) => patch({ other: e.target.value })}
          rows={2}
          placeholder="请输入你的答案"
          className="mt-2 w-full resize-none rounded-[var(--radius-field)] border border-base-300 bg-base-100 px-2.5 py-2 text-[14px] text-base-content outline-none focus:border-primary/50"
        />
      )}

      <div className="mt-2.5 flex items-center justify-between gap-2">
        <button
          onClick={() => go(-1)}
          disabled={index === 0}
          className="btn btn-xs gap-1 border-base-300 bg-base-100 text-base-content/90 disabled:opacity-40"
        >
          <ArrowLeft className="h-3 w-3" />
          上一问
        </button>

        {isLast ? (
          <button
            onClick={() => canAdvance && onSubmit(answers)}
            disabled={!canAdvance}
            className="btn btn-xs gap-1 border-primary/40 bg-primary text-white disabled:opacity-40"
          >
            <Send className="h-3 w-3" />
            提交
          </button>
        ) : (
          <button
            onClick={() => go(1)}
            disabled={!canAdvance}
            className="btn btn-xs gap-1 border-primary/40 bg-primary text-white disabled:opacity-40"
          >
            下一问
            <ArrowRight className="h-3 w-3" />
          </button>
        )}
      </div>
    </div>
  );
}
