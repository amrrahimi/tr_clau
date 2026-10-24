// Language handling: picks the text for a key and remembers the user's choice.

import { en, type MessageKey } from "./locales/en.ts";
import { fa } from "./locales/fa.ts";

export type Language = "fa" | "en";
export const DEFAULT_LANGUAGE: Language = "fa";

const MESSAGES: Record<Language, Record<MessageKey, string>> = { fa, en };
const STORAGE_KEY = "trading-bot.language";

export function direction(language: Language): "rtl" | "ltr" {
  return language === "fa" ? "rtl" : "ltr";
}

/** Text for a key, with {name} placeholders filled in. */
export function translate(language: Language, key: MessageKey, params: Record<string, string> = {}): string {
  const template = MESSAGES[language][key] ?? en[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => params[name] ?? match);
}

/** The saved language, or the default. Storage can be missing or blocked. */
export function loadLanguage(storage: Pick<Storage, "getItem"> | undefined = safeStorage()): Language {
  try {
    const saved = storage?.getItem(STORAGE_KEY);
    return saved === "fa" || saved === "en" ? saved : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

export function saveLanguage(language: Language, storage: Pick<Storage, "setItem"> | undefined = safeStorage()): void {
  try {
    storage?.setItem(STORAGE_KEY, language);
  } catch {
    // Not being able to remember the language is not worth an error message.
  }
}

function safeStorage(): Storage | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}
