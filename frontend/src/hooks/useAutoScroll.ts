"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface AutoScroll {
  /** 挂到滚动容器上 */
  scrollRef: React.RefObject<HTMLDivElement | null>;
  /** 是否正在自动跟随底部（false 时显示「回到底部」） */
  autoFollow: boolean;
  jumpToBottom: () => void;
}

/**
 * 统一的「流式内容自动下滑」逻辑：对话主区与智能体窗口共用。
 *
 * 行为：
 *   - 内容变化时，若用户停在底部（阈值内）则自动滚到底；
 *   - 用户手动往上滚 → 停止跟随，避免抢走阅读位置；
 *   - 点「回到底部」→ 重新跟随。
 *
 * @param deps 触发重新贴底的内容依赖（如 messages / agent.items），引用变化即检查
 * @param threshold 距底部多少 px 以内算「贴底」
 */
export function useAutoScroll(deps: unknown[], threshold = 40): AutoScroll {
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const [autoFollow, setAutoFollow] = useState(true);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const stick = el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
      stickRef.current = stick;
      setAutoFollow(stick);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [threshold]);

  useEffect(() => {
    if (!stickRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    // 依赖由调用方给出（内容引用变化即尝试贴底）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const jumpToBottom = useCallback(() => {
    stickRef.current = true;
    setAutoFollow(true);
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  return { scrollRef, autoFollow, jumpToBottom };
}
