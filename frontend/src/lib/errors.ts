import { ApiError, IssueDetail } from "@/lib/api";
import { TranslationKey, translate } from "@/i18n";

const issueTranslationKeys: Partial<Record<string, TranslationKey>> = {
  CLIENT_REQUEST_TIMEOUT: "errors.timeout",
  AUTH_NOT_AUTHENTICATED: "errors.authNotAuthenticated",
  AUTH_INVALID_PASSWORD: "errors.authInvalidPassword",
  ACCOUNT_NOT_FOUND: "errors.accountNotFound",
  ACCOUNT_AUTH_NOT_FOUND: "errors.accountAuthNotFound",
  ACCOUNT_HIDE_CURRENT_FORBIDDEN: "errors.accountHideCurrentForbidden",
  ACCOUNT_INVALID_ID: "errors.accountInvalidId",
  ACCOUNT_AUTH_TOKENS_MISSING: "errors.accountAuthTokensMissing",
  ACCOUNT_AUTH_ACCOUNT_ID_MISSING: "errors.accountAuthAccountIdMissing",
  ACCOUNT_AUTH_ACCESS_TOKEN_MISSING: "errors.accountAuthAccessTokenMissing",
  ACCOUNT_STORED_AUTH_MISMATCH: "errors.accountStoredAuthMismatch",
  ACCOUNT_INVALID_REQUEST: "errors.accountInvalidRequest",
  ACCOUNT_SCAN_WARNING: "errors.accountScanWarning",
  CONFIG_IMPORT_INVALID_PAYLOAD: "errors.configImportInvalidPayload",
  CONFIG_IMPORT_INVALID_SCHEMA: "errors.configImportInvalidSchema",
  CONFIG_IMPORT_ACCOUNTS_NOT_LIST: "errors.configImportAccountsNotList",
  CONFIG_IMPORT_ACCOUNT_ITEM_INVALID: "errors.configImportAccountItemInvalid",
  CONFIG_IMPORT_ACCOUNT_ID_REQUIRED: "errors.configImportAccountIdRequired",
  CONFIG_IMPORT_ACCOUNT_ID_INVALID: "errors.configImportAccountIdInvalid",
  CONFIG_IMPORT_HIDDEN_INVALID: "errors.configImportHiddenInvalid",
  CONFIG_IMPORT_FIELD_TYPE_INVALID: "errors.configImportFieldTypeInvalid",
  CONFIG_IMPORT_LIMIT_INVALID: "errors.configImportLimitInvalid",
  CONFIG_IMPORT_INVALID: "errors.configImportInvalid",
  SESSIONS_INVALID_CURSOR: "errors.sessionsInvalidCursor",
  SESSIONS_INVALID_EVENT_CURSOR: "errors.sessionsInvalidEventCursor",
  SESSIONS_INVALID_PAGE: "errors.sessionsInvalidPage",
  SESSIONS_NOT_FOUND: "errors.sessionsNotFound",
  SESSIONS_EVENT_NOT_FOUND: "errors.sessionsEventNotFound",
  SESSIONS_EVENT_LINE_METADATA_MISSING: "errors.sessionsEventLineMetadataMissing",
  SESSIONS_INVALID_REQUEST: "errors.sessionsInvalidRequest",
  USAGE_INVALID_CURSOR: "errors.usageInvalidCursor",
  USAGE_INVALID_PAGE: "errors.usageInvalidPage",
  USAGE_INVALID_REQUEST: "errors.usageInvalidRequest",
  IMAGE_PROMPT_REQUIRED: "errors.imagePromptRequired",
  IMAGE_PROMPT_TOO_LONG: "errors.imagePromptTooLong",
  IMAGE_INVALID_SIZE: "errors.imageInvalidSize",
  IMAGE_INVALID_QUALITY: "errors.imageInvalidQuality",
  IMAGE_INVALID_RESPONSE_FORMAT: "errors.imageInvalidResponseFormat",
  IMAGE_REFERENCE_TOO_MANY: "errors.imageReferenceTooMany",
  IMAGE_REFERENCE_INVALID: "errors.imageReferenceInvalid",
  IMAGE_REFERENCE_TOO_LARGE: "errors.imageReferenceTooLarge",
  IMAGE_REFERENCE_UNSUPPORTED_TYPE: "errors.imageReferenceUnsupportedType",
  IMAGE_AUTH_NOT_FOUND: "errors.imageAuthNotFound",
  IMAGE_AUTH_TOKENS_MISSING: "errors.imageAuthTokensMissing",
  IMAGE_AUTH_ACCOUNT_ID_MISSING: "errors.imageAuthAccountIdMissing",
  IMAGE_AUTH_ACCESS_TOKEN_MISSING: "errors.imageAuthAccessTokenMissing",
  IMAGE_AUTH_INVALID: "errors.imageAuthInvalid",
  IMAGE_UPSTREAM_TIMEOUT: "errors.imageUpstreamTimeout",
  IMAGE_UPSTREAM_ERROR: "errors.imageUpstreamError",
  IMAGE_JOB_NOT_FOUND: "errors.imageJobNotFound",
  IMAGE_CONVERSATION_NOT_FOUND: "errors.imageConversationNotFound",
  IMAGE_INVALID_REQUEST: "errors.imageInvalidRequest",
};

export function formatIssueMessage(issue: IssueDetail | null | undefined): string | null {
  if (!issue) return null;
  const key = issueTranslationKeys[issue.code];
  return key ? translate(key) : issue.message;
}

export function formatAppError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code) {
      const key = issueTranslationKeys[error.code];
      if (key) return translate(key);
    }
    return error.message || translate("errors.generic");
  }
  if (error instanceof Error) {
    return error.message || translate("errors.generic");
  }
  return translate("errors.generic");
}
