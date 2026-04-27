import { createContext, ReactNode, useContext, useState } from "react";

export type Locale = "en" | "zh-CN";

type InterpolationValue = string | number;

const STORAGE_KEY = "switchboard.locale";
const DEFAULT_LOCALE: Locale = "en";

const en = {
  "common.loading": "Loading",
  "common.loadingEllipsis": "Loading...",
  "common.notAvailable": "n/a",
  "common.unknown": "Unknown",
  "common.pageLabel": "Page {page} / {total}",
  "common.selectPage": "Select page",
  "common.previousPage": "Previous page",
  "common.nextPage": "Next page",
  "language.label": "Language",
  "language.englishShort": "EN",
  "language.chineseShort": "中文",
  "app.subtitle": "Local Codex console",
  "login.subtitle": "Codex console",
  "login.passwordPlaceholder": "Password",
  "login.signIn": "Sign in",
  "nav.dashboard": "Dashboard",
  "nav.sessions": "Sessions",
  "nav.requestLogs": "Request Logs",
  "nav.signOut": "Sign out",
  "errorBoundary.title": "SwitchBoard hit an unexpected error",
  "errorBoundary.subtitle": "The app can recover by reloading cleanly.",
  "errorBoundary.description": "A component crashed while rendering. Reload the application to rebuild the dashboard state.",
  "errorBoundary.reloadApp": "Reload app",
  "accounts.title": "Accounts",
  "accounts.noCurrentAccount": "No current account",
  "accounts.collapse": "Collapse accounts",
  "accounts.expand": "Expand accounts",
  "accounts.importConfig": "Import config",
  "accounts.exportConfig": "Export config",
  "accounts.scan": "Scan",
  "accounts.current": "Current",
  "accounts.expired": "Expired",
  "accounts.customNamePlaceholder": "Custom name",
  "accounts.saveName": "Save name",
  "accounts.cancelRename": "Cancel rename",
  "accounts.switchAccount": "Switch account",
  "accounts.renameAccount": "Rename account",
  "accounts.hideAccount": "Hide account",
  "accounts.fiveHourRemaining": "5h remaining",
  "accounts.weeklyRemaining": "Weekly remaining",
  "accounts.lastScanFailed": "Last scan failed",
  "accounts.lastScanFailedCount": "Last scan failed x{count}",
  "accounts.switchingTo": "Switching to {name}",
  "accounts.scanWarningTitle": "Scan warning",
  "accounts.accountSwitched": "Account switched",
  "accounts.accountSwitchedDescription": "Switched to {name}. Restart Codex for the change to take effect.",
  "accounts.switchFailed": "Switch failed",
  "accounts.switchFailedFallback": "Unable to switch account.",
  "accounts.exportingConfig": "Exporting config",
  "accounts.configExported": "Config exported",
  "accounts.configExportedDescription": "{count} account preferences saved.",
  "accounts.exportFailed": "Export failed",
  "accounts.exportFailedFallback": "Unable to export config.",
  "accounts.configImported": "Config imported",
  "accounts.configImportedDescription": "{imported} imported ({created} created, {updated} updated).",
  "accounts.importFailed": "Import failed",
  "accounts.importFailedFallback": "Unable to import config.",
  "accounts.renameFailedFallback": "Rename failed",
  "accounts.defaultName": "account",
  "sessions.title": "Sessions",
  "sessions.searchPlaceholder": "Search sessions",
  "sessions.noSessionsOnPage": "No sessions on this page",
  "sessions.noSessions": "No sessions",
  "sessions.sessionDetail": "Session detail",
  "sessions.eventsFromRaw": "{eventCount} events from {rawCount} raw lines",
  "sessions.noSessionSelected": "No session selected",
  "sessions.noEventContent": "No event content",
  "sessions.eventsTimeline": "Events Timeline",
  "sessions.showingEvents": "Showing {shown} of {total} events",
  "sessions.loadMore": "Loading more",
  "sessions.scrollToLoadMore": "Scroll to load more",
  "sessions.userMessages": "User Messages",
  "sessions.noUserMessages": "No user messages",
  "sessions.loadingIndex": "Loading index",
  "sessions.loadFullWithSize": "Load full - {size}",
  "sessions.collapseWithSize": "Collapse - {size}",
  "sessions.line": "line {line}",
  "sessions.user": "user",
  "sessions.assistant": "assistant",
  "sessions.system": "system",
  "sessions.emptyUserMessage": "Empty user message",
  "usage.title": "Usage",
  "usage.input": "Input",
  "usage.cacheHit": "Cache hit",
  "usage.output": "Output",
  "usage.cacheCreated": "Cache created",
  "usage.noUsageInRange": "No usage in range",
  "requestLogs.title": "Request Logs",
  "requestLogs.totalRequests": "Total requests",
  "requestLogs.totalCost": "Total cost",
  "requestLogs.totalTokens": "Total tokens",
  "requestLogs.cacheTokens": "Cache tokens",
  "requestLogs.requestsTitle": "Codex Requests",
  "requestLogs.rows": "{count} rows",
  "requestLogs.noLogsInRange": "No request logs in range",
  "requestLogs.time": "Time",
  "requestLogs.billingModel": "Billing model",
  "requestLogs.totalCostColumn": "Total cost",
  "requestLogs.cacheWithCount": "Cache {count}",
  "requestLogs.reasoningWithCount": "Reasoning {count}",
  "requestLogs.tokensWithCount": "{count} tokens",
  "errors.generic": "Something went wrong.",
  "errors.timeout": "The request timed out.",
  "errors.authNotAuthenticated": "Not authenticated",
  "errors.authInvalidPassword": "Invalid password",
  "errors.accountNotFound": "Account not found",
  "errors.accountAuthNotFound": "Account auth not found",
  "errors.accountHideCurrentForbidden": "Cannot hide the current Codex account",
  "errors.accountInvalidId": "Invalid account_id",
  "errors.accountAuthTokensMissing": "auth.json does not contain ChatGPT tokens",
  "errors.accountAuthAccountIdMissing": "auth.json does not contain tokens.account_id",
  "errors.accountAuthAccessTokenMissing": "auth.json does not contain tokens.access_token",
  "errors.accountStoredAuthMismatch": "Stored auth account_id does not match requested account",
  "errors.accountInvalidRequest": "Account operation failed.",
  "errors.accountScanWarning": "Account scan completed with a warning.",
  "errors.configImportInvalidPayload": "Config import must be a JSON object.",
  "errors.configImportInvalidSchema": "Unsupported config schema.",
  "errors.configImportAccountsNotList": "accounts must be a list.",
  "errors.configImportAccountItemInvalid": "Each config account item must be an object.",
  "errors.configImportAccountIdRequired": "account_id must be a non-empty string.",
  "errors.configImportAccountIdInvalid": "account_id is invalid.",
  "errors.configImportHiddenInvalid": "hidden must be a boolean.",
  "errors.configImportFieldTypeInvalid": "Config import contains a field with the wrong type.",
  "errors.configImportLimitInvalid": "Config import contains an invalid limit value.",
  "errors.configImportInvalid": "Config import is invalid.",
  "errors.sessionsInvalidCursor": "Invalid cursor",
  "errors.sessionsInvalidEventCursor": "Invalid event cursor",
  "errors.sessionsInvalidPage": "Invalid page",
  "errors.sessionsNotFound": "Session not found",
  "errors.sessionsEventNotFound": "Session event not found",
  "errors.sessionsEventLineMetadataMissing": "Session event is missing line metadata",
  "errors.sessionsInvalidRequest": "Session request is invalid.",
  "errors.usageInvalidCursor": "Invalid cursor",
  "errors.usageInvalidPage": "Invalid page",
  "errors.usageInvalidRequest": "Usage request is invalid.",
} as const;

export type TranslationKey = keyof typeof en;

const zhCN: Record<TranslationKey, string> = {
  "common.loading": "加载中",
  "common.loadingEllipsis": "加载中...",
  "common.notAvailable": "不可用",
  "common.unknown": "未知",
  "common.pageLabel": "第 {page} / {total} 页",
  "common.selectPage": "选择页码",
  "common.previousPage": "上一页",
  "common.nextPage": "下一页",
  "language.label": "语言",
  "language.englishShort": "EN",
  "language.chineseShort": "中文",
  "app.subtitle": "本地 Codex 控制台",
  "login.subtitle": "Codex 控制台",
  "login.passwordPlaceholder": "密码",
  "login.signIn": "登录",
  "nav.dashboard": "仪表盘",
  "nav.sessions": "会话",
  "nav.requestLogs": "请求日志",
  "nav.signOut": "退出登录",
  "errorBoundary.title": "SwitchBoard 遇到了意外错误",
  "errorBoundary.subtitle": "重新加载后通常可以恢复。",
  "errorBoundary.description": "某个组件在渲染时崩溃了。重新加载应用以重建仪表盘状态。",
  "errorBoundary.reloadApp": "重新加载",
  "accounts.title": "账号",
  "accounts.noCurrentAccount": "当前没有生效账号",
  "accounts.collapse": "收起账号列表",
  "accounts.expand": "展开账号列表",
  "accounts.importConfig": "导入配置",
  "accounts.exportConfig": "导出配置",
  "accounts.scan": "扫描",
  "accounts.current": "当前",
  "accounts.expired": "已失效",
  "accounts.customNamePlaceholder": "自定义名称",
  "accounts.saveName": "保存名称",
  "accounts.cancelRename": "取消重命名",
  "accounts.switchAccount": "切换账号",
  "accounts.renameAccount": "重命名账号",
  "accounts.hideAccount": "隐藏账号",
  "accounts.fiveHourRemaining": "5 小时剩余",
  "accounts.weeklyRemaining": "每周剩余",
  "accounts.lastScanFailed": "上次扫描失败",
  "accounts.lastScanFailedCount": "上次扫描失败 x{count}",
  "accounts.switchingTo": "正在切换到 {name}",
  "accounts.scanWarningTitle": "扫描警告",
  "accounts.accountSwitched": "账号已切换",
  "accounts.accountSwitchedDescription": "已切换到 {name}。重启 Codex 后生效。",
  "accounts.switchFailed": "切换失败",
  "accounts.switchFailedFallback": "无法切换账号。",
  "accounts.exportingConfig": "正在导出配置",
  "accounts.configExported": "配置已导出",
  "accounts.configExportedDescription": "已保存 {count} 个账号偏好。",
  "accounts.exportFailed": "导出失败",
  "accounts.exportFailedFallback": "无法导出配置。",
  "accounts.configImported": "配置已导入",
  "accounts.configImportedDescription": "已导入 {imported} 个（新建 {created} 个，更新 {updated} 个）。",
  "accounts.importFailed": "导入失败",
  "accounts.importFailedFallback": "无法导入配置。",
  "accounts.renameFailedFallback": "重命名失败",
  "accounts.defaultName": "账号",
  "sessions.title": "会话",
  "sessions.searchPlaceholder": "搜索会话",
  "sessions.noSessionsOnPage": "这一页没有会话",
  "sessions.noSessions": "没有会话",
  "sessions.sessionDetail": "会话详情",
  "sessions.eventsFromRaw": "{eventCount} 个事件，来自 {rawCount} 行原始数据",
  "sessions.noSessionSelected": "未选择会话",
  "sessions.noEventContent": "没有事件内容",
  "sessions.eventsTimeline": "事件时间线",
  "sessions.showingEvents": "已显示 {shown} / {total} 个事件",
  "sessions.loadMore": "正在加载更多",
  "sessions.scrollToLoadMore": "滚动以加载更多",
  "sessions.userMessages": "用户消息",
  "sessions.noUserMessages": "没有用户消息",
  "sessions.loadingIndex": "正在加载索引",
  "sessions.loadFullWithSize": "加载完整内容 - {size}",
  "sessions.collapseWithSize": "收起 - {size}",
  "sessions.line": "第 {line} 行",
  "sessions.user": "用户",
  "sessions.assistant": "助手",
  "sessions.system": "系统",
  "sessions.emptyUserMessage": "空用户消息",
  "usage.title": "用量",
  "usage.input": "输入",
  "usage.cacheHit": "缓存命中",
  "usage.output": "输出",
  "usage.cacheCreated": "缓存创建",
  "usage.noUsageInRange": "当前区间没有用量数据",
  "requestLogs.title": "请求日志",
  "requestLogs.totalRequests": "总请求数",
  "requestLogs.totalCost": "总成本",
  "requestLogs.totalTokens": "总 Token 数",
  "requestLogs.cacheTokens": "缓存 Token",
  "requestLogs.requestsTitle": "Codex 请求",
  "requestLogs.rows": "{count} 行",
  "requestLogs.noLogsInRange": "当前区间没有请求日志",
  "requestLogs.time": "时间",
  "requestLogs.billingModel": "计费模型",
  "requestLogs.totalCostColumn": "总成本",
  "requestLogs.cacheWithCount": "缓存 {count}",
  "requestLogs.reasoningWithCount": "推理 {count}",
  "requestLogs.tokensWithCount": "{count} 个 tokens",
  "errors.generic": "发生了错误。",
  "errors.timeout": "请求超时。",
  "errors.authNotAuthenticated": "未登录",
  "errors.authInvalidPassword": "密码无效",
  "errors.accountNotFound": "未找到账号",
  "errors.accountAuthNotFound": "未找到账号认证信息",
  "errors.accountHideCurrentForbidden": "不能隐藏当前生效的 Codex 账号",
  "errors.accountInvalidId": "账号 ID 无效",
  "errors.accountAuthTokensMissing": "auth.json 中缺少 ChatGPT tokens",
  "errors.accountAuthAccountIdMissing": "auth.json 中缺少 tokens.account_id",
  "errors.accountAuthAccessTokenMissing": "auth.json 中缺少 tokens.access_token",
  "errors.accountStoredAuthMismatch": "已保存的 auth 账号 ID 与请求的账号不一致",
  "errors.accountInvalidRequest": "账号操作失败。",
  "errors.accountScanWarning": "账号扫描完成，但有警告。",
  "errors.configImportInvalidPayload": "配置导入内容必须是 JSON 对象。",
  "errors.configImportInvalidSchema": "配置导入 schema 不受支持。",
  "errors.configImportAccountsNotList": "accounts 必须是列表。",
  "errors.configImportAccountItemInvalid": "配置中的账号项必须是对象。",
  "errors.configImportAccountIdRequired": "account_id 必须是非空字符串。",
  "errors.configImportAccountIdInvalid": "account_id 无效。",
  "errors.configImportHiddenInvalid": "hidden 必须是布尔值。",
  "errors.configImportFieldTypeInvalid": "配置导入中存在类型不正确的字段。",
  "errors.configImportLimitInvalid": "配置导入中存在无效的限制值。",
  "errors.configImportInvalid": "配置导入无效。",
  "errors.sessionsInvalidCursor": "游标无效",
  "errors.sessionsInvalidEventCursor": "事件游标无效",
  "errors.sessionsInvalidPage": "页码无效",
  "errors.sessionsNotFound": "未找到会话",
  "errors.sessionsEventNotFound": "未找到会话事件",
  "errors.sessionsEventLineMetadataMissing": "会话事件缺少行元数据",
  "errors.sessionsInvalidRequest": "会话请求无效。",
  "errors.usageInvalidCursor": "游标无效",
  "errors.usageInvalidPage": "页码无效",
  "errors.usageInvalidRequest": "用量请求无效。",
};

const translations: Record<Locale, Record<TranslationKey, string>> = {
  en,
  "zh-CN": zhCN,
};

let currentLocale: Locale = DEFAULT_LOCALE;

type I18nContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey, params?: Record<string, InterpolationValue>) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function normalizeLocale(value: string | null | undefined): Locale {
  if (typeof value === "string" && value.toLowerCase().startsWith("zh")) return "zh-CN";
  return DEFAULT_LOCALE;
}

function storedLocale(): Locale | null {
  if (typeof window === "undefined") return null;
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value ? normalizeLocale(value) : null;
  } catch {
    return null;
  }
}

function browserLocale(): Locale {
  if (typeof navigator === "undefined") return DEFAULT_LOCALE;
  const candidates = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const candidate of candidates) {
    if (candidate) return normalizeLocale(candidate);
  }
  return DEFAULT_LOCALE;
}

function syncLocale(locale: Locale, persistSelection: boolean) {
  currentLocale = locale;
  if (typeof document !== "undefined") {
    document.documentElement.lang = locale;
  }
  if (persistSelection && typeof window !== "undefined") {
    try {
      window.localStorage.setItem(STORAGE_KEY, locale);
    } catch {
      // Ignore storage failures and keep in-memory locale.
    }
  }
}

export function setCurrentLocale(locale: Locale, persistSelection = false) {
  syncLocale(locale, persistSelection);
}

export function getCurrentLocale(): Locale {
  return currentLocale;
}

export function initializeLocale(): Locale {
  const locale = storedLocale() ?? browserLocale();
  syncLocale(locale, false);
  return locale;
}

export function translate(
  key: TranslationKey,
  params: Record<string, InterpolationValue> = {},
  locale: Locale = currentLocale,
) {
  const template = translations[locale][key] ?? translations.en[key] ?? key;
  return template.replace(/\{(\w+)\}/g, (_, token: string) => String(params[token] ?? `{${token}}`));
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => initializeLocale());

  function setLocale(nextLocale: Locale) {
    syncLocale(nextLocale, true);
    setLocaleState(nextLocale);
  }

  function t(key: TranslationKey, params?: Record<string, InterpolationValue>) {
    return translate(key, params, locale);
  }

  return <I18nContext.Provider value={{ locale, setLocale, t }}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error("useI18n must be used within I18nProvider");
  }
  return context;
}