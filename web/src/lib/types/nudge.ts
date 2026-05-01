export type ReminderType = "once" | "recurring" | "event";
export type ReminderStatus = "active" | "paused" | "awaiting" | "done" | "expired";

export interface Reminder {
  id: string;
  title: string;
  shortName?: string | null;
  body?: string | null;
  type: ReminderType;
  fireAt?: string | null;
  cronExpression?: string | null;
  timezone: string;
  triggerSource?: string | null;
  triggerCondition?: object | null;
  status: ReminderStatus;
  lastFiredAt?: string | null;
  firstFiredAt?: string | null;
  nextFireAt?: string | null;
  ackRetries?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ParsedReminder {
  title: string;
  body?: string | null;
  type: ReminderType;
  fireAt?: string | null;
  cronExpression?: string | null;
  timezone: string;
}

export interface ParseResponse {
  reminder: ParsedReminder;
  confidence: number;
  rawInterpretation: string;
  nextFireAt?: string | null;
}

export interface NoteEntities {
  people: string[];
  places: string[];
  orgs: string[];
}

export interface Note {
  id: string;
  shortId?: number | null;
  title?: string | null;
  content: string;
  tags?: string[] | null;
  entities?: NoteEntities | null;
  relatedIds?: number[] | null;
  triggerSource?: string | null;
  status: "active" | "archived";
  createdAt: string;
  updatedAt: string;
}

export interface ReminderCreate {
  title: string;
  body?: string | null;
  type: ReminderType;
  fireAt?: string | null;
  cronExpression?: string | null;
  timezone: string;
  triggerSource?: string | null;
  triggerCondition?: object | null;
}
