export type Secret = { is_set: boolean; hint: string }

export type ProtectedFriend = { steam_id: string; note: string }

export type Settings = {
  funpay: {
    golden_key: Secret
    user_agent: string
    auto_raise: boolean
    raise_categories: number[]
  }
  steam: { api_key: Secret; steam_id: string; login_secure: Secret }
  friends: {
    protected: ProtectedFriend[]
    refresh_hours: number
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

export type SteamFriend = {
  steam_id: string
  relationship: 'friend' | 'invite_sent' | 'invite_received'
  name: string
  friend_since: string | null
  avatar: string
}

export type RankedFriend = {
  friend: SteamFriend
  tier: string
  rank: number
  buyer_name: string
  last_order_at: string | null
  orders: number
}

export type FriendsReport = {
  own_level: number | null
  limit: number | null
  used: number
  ranked: RankedFriend[]
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

export type SalePreview = {
  order_id: string
  title: string
  buyer_name: string
  price: number
  currency: string
  status: string
  date_text: string
}

export type SalesSnapshot = {
  items: SalePreview[]
  refreshed_at: string | null
  refreshing: boolean
  error: string
  interval_seconds: number
}
