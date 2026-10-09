/** Shared wire-protocol types (camelCase envelope, D-18). */

export type WireEnvelope<TType extends string = string> = {
  type: TType;
  payload: Record<string, unknown>;
  requestId?: string;
};
