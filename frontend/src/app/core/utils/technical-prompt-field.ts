/**
 * A technical prompt goes to the server only when the form holds one: a save that
 * never loaded the prompt must not wipe it. An empty string is sent — it means the
 * built-in prompt.
 */
export const promptField = (key: string, value: string | undefined): Record<string, string> =>
    typeof value === 'string' ? { [key]: value } : {};
