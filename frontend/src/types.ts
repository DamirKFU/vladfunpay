export type Secret = { is_set: boolean; hint: string }

export type ReplyTemplate = { examples: string[]; keywords: string[]; reply: string }
export type ReplyExample = { buyer: string; reply: string }
export type ProductKind = 'gift' | 'trade' | 'account' | 'manual'
export type ProductType = {
  id: string
  name: string
  kind: ProductKind
  description: string
  instructions: string
  keywords: string[]
  handoff_keywords: string[]
  friend_days: number
  per_day: number
  send_hours: number
}
export type LotRecord = {
  channel: Channel
  lot_id: string
  title: string
  description: string
  type_id: string
  assigned_by: '' | 'manual' | 'keywords' | 'ai' | 'default'
  amount: number | null
  auto_delivery: boolean
  price: number
  updated_at: string | null
}
export type ProtectedFriend = { steam_id: string; note: string }

export type Settings = {
  funpay: {
    golden_key: Secret
    user_agent: string
    offer_subcategories: number[]
    auto_raise: boolean
    raise_categories: number[]
  }
  yandex: {
    api_key: Secret
    folder_id: string
    model: string
    base_url: string
    temperature: number
  }
  steam: { api_key: Secret; steam_id: string; login_secure: Secret; session_id: Secret }
  bot: {
    enabled: boolean
    poll_interval_sec: number
    reply_delay_sec: number
    max_wait_sec: number
    max_tokens: number
    daily_token_limit: number
    chat_daily_replies: number
    only_with_open_orders: boolean
    max_input_chars: number
    history_messages: number
    seller_notes: string
    handoff_reply: string
    style_prompt: string
    examples: ReplyExample[]
    templates: ReplyTemplate[]
    template_threshold: number
  }
  friends: {
    protected: ProtectedFriend[]
    keep_free_slots: number
    long_friend_days: number
    auto_cleanup: boolean
    refresh_hours: number
    allow_removal: boolean
  }
  catalog: {
    types: ProductType[]
    default_type: string
    classify_with_ai: boolean
  }
  telegram: {
    bot_token: Secret
    chat_id: string
    notify_tool_errors: boolean
    notify_handoff: boolean
    notify_sandbox: boolean
  }
}

export type RaiseCategory = {
  category_id: number
  next_at: string | null
  last_at: string | null
  ok: boolean | null
  message: string
}
export type RaiseStatus = { enabled: boolean; categories: RaiseCategory[] }

export type PromptInfo = { tool_rules: string; default_style: string; composed: string }
export type SandboxFriendship = { relationship: 'friend' | 'invite_sent' | 'invite_received' | null; since: string | null }

export type SyncRun = {
  id: string
  status: 'running' | 'done' | 'error'
  started_at: string
  finished_at: string | null
  date_from: string | null
  date_to: string
  fetched: number
  message: string
}

export type WorkerState = {
  running: boolean
  active: boolean
  last_poll_at: string | null
  last_error: string
  pending_chats: string[]
}

export type BotStatus = {
  enabled: boolean
  funpay: WorkerState
  sandbox: WorkerState
  tokens_today: number
  daily_token_limit: number
  llm_configured: boolean
  funpay_configured: boolean
}

export type Channel = 'funpay' | 'sandbox'

export type Conversation = {
  channel: Channel
  chat_id: string
  buyer_id: number | null
  buyer_name: string
  last_message_at: string
  needs_human: boolean
  human_reason: string
  replies_today: number
}

export type ChatMessage = {
  chat_id: string
  message_id: number
  author: 'buyer' | 'bot' | 'seller' | 'system'
  text: string
  created_at: string
}

export type ToolCallTrace = { name: string; arguments: Record<string, unknown>; result: unknown }

export type BotTrace = {
  created_at: string
  input_text: string
  reply: string | null
  outcome: 'replied' | 'template' | 'handoff' | 'skipped' | 'discarded' | 'error'
  detail: string
  tool_calls: ToolCallTrace[]
  tokens: number
}

export type ChatView = {
  conversation: Conversation
  messages: ChatMessage[]
  traces: BotTrace[]
}

export type Offer = {
  offer_id: string
  title: string
  price: number
  amount: number | null
  category: string
  auto_delivery: boolean
  description: string
}

export type OpenOrder = {
  order_id: string
  title: string
  price: number
  buyer_id: number | null
  buyer_name: string
  status: string
}

export type SteamFriend = {
  steam_id: string
  relationship: 'friend' | 'invite_sent' | 'invite_received'
  name: string
  level: number | null
  friend_since: string | null
  avatar: string
}

export type RankedFriend = {
  friend: SteamFriend
  tier: string
  rank: number
  removable: boolean
  reason: string
  buyer_name: string
  last_order_at: string | null
  orders: number
}

export type FriendsReport = {
  own_level: number | null
  limit: number | null
  used: number
  keep_free: number
  to_free: number
  ranked: RankedFriend[]
  candidates: RankedFriend[]
  refreshed_at: string | null
}

export type LogEntry = {
  ts: string
  level: string
  source: string
  message: string
  context: Record<string, unknown>
}

export type User = { username: string; created_at: string }
