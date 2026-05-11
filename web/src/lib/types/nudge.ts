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

export interface ThreadEntities {
  people: string[];
  places: string[];
  orgs: string[];
}

export type TriggerType = "none" | "once" | "recurring" | "geofence";
export type AckStatus =
  | "pending"
  | "firing"
  | "awaiting"
  | "acknowledged"
  | "snoozed"
  | "dismissed"
  | "expired";

export interface Trigger {
  type: TriggerType;
  fire_at?: string | null;
  cron?: string | null;
  location?: string | null;
  ack_status: AckStatus;
  ack_timeout_at?: string | null;
}

export interface Thread {
  id: string;
  shortId?: number | null;
  title?: string | null;
  content: string;
  category?: "pro" | "life" | "emo" | "routine" | null;
  tags?: string[] | null;
  entities?: ThreadEntities | null;
  relatedIds?: number[] | null;
  triggerSource?: string | null;
  trigger?: Trigger | null;
  snoozeCount?: number | null;
  source?: string | null;
  priority?: "high" | "normal" | "low" | null;
  status: "active" | "sleeping" | "archived";
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
