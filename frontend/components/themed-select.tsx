"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

export type ThemedSelectOption = { value: string; label: string };

export function ThemedSelect({
  value,
  options,
  onChange,
  className = "",
  ariaLabel,
  disabled = false,
}: {
  value: string;
  options: ThemedSelectOption[];
  onChange: (value: string) => void;
  className?: string;
  ariaLabel?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState<"down" | "up">("down");
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value) || options[0];

  useLayoutEffect(() => {
    if (!open) return;
    const reposition = () => {
      const trigger = triggerRef.current?.getBoundingClientRect();
      const menuElement = menuRef.current;
      const menu = menuElement?.getBoundingClientRect();
      if (!trigger || !menu || !menuElement) return;
      const margin = 10;
      const spaceBelow = window.innerHeight - trigger.bottom - margin;
      const spaceAbove = trigger.top - margin;
      const nextPlacement = menu.height > spaceBelow && spaceAbove > spaceBelow ? "up" : "down";
      setPlacement(nextPlacement);
      const availableSpace = nextPlacement === "up" ? spaceAbove : spaceBelow;
      menuElement.style.maxHeight = `${Math.max(48, Math.min(240, availableSpace))}px`;
    };
    reposition();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
    };
  }, [open, options.length]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  const choose = (nextValue: string) => {
    onChange(nextValue);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const handleTriggerKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen(true);
    }
  };

  return (
    <div ref={rootRef} className={`themed-select${open ? " open" : ""}${open && placement === "up" ? " open-up" : ""}${className ? ` ${className}` : ""}`}>
      <button
        ref={triggerRef}
        type="button"
        className="themed-select-trigger"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled || !selected}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={handleTriggerKeyDown}
      >
        <span>{selected?.label || "Select"}</span>
      </button>
      {open && selected && (
        <div ref={menuRef} className="themed-select-menu" role="listbox" aria-label={ariaLabel}>
          {options.map((option) => (
            <button
              type="button"
              role="option"
              aria-selected={option.value === value}
              className="themed-select-option"
              key={option.value}
              onClick={() => choose(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
