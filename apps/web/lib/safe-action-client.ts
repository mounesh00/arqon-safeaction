/** Browser-only UI state. No credentials, sessions or decisions are simulated. */
export type SafeActionProposal = Readonly<{
  proposal_id: string; title: string; items: readonly string[]; fingerprint: string;
  expires_at: string; status: 'pending' | 'approved' | 'rejected' | 'expired';
}>;
export type SafeActionState = Readonly<{
  expires: string | null; proposal: SafeActionProposal | null; busy: boolean;
  reviewed: boolean; confirmation: 'approve' | 'reject' | null;
  needsRefresh: boolean; message: string; error: boolean;
}>;
const UUID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
class Failure extends Error {
  constructor(readonly status: number, readonly code = '') { super('SafeAction request failed'); }
}
export class SafeActionClient {
  private state: SafeActionState = { expires: null, proposal: null, busy: false,
    reviewed: false, confirmation: null, needsRefresh: false,
    message: 'Sign in to review a checklist. No operator data has been loaded.', error: false };
  private csrf = '';
  private listeners = new Set<() => void>();
  constructor(private fetcher: typeof fetch = (...args) => fetch(...args), private clock = () => Date.now()) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(change: Partial<SafeActionState>) {
    this.state = Object.freeze({ ...this.state, ...change }); this.listeners.forEach(fn => fn());
  }
  private clear(message: string, error = false) {
    this.csrf = ''; this.update({ expires: null, proposal: null, reviewed: false,
      confirmation: null, needsRefresh: false, message, error });
  }
  expire = () => {
    if (this.state.expires && Date.parse(this.state.expires) <= this.clock()) {
      this.clear('Operator session expired. Sign in again.', true);
    } else if (this.state.proposal?.status === 'pending' && Date.parse(this.state.proposal.expires_at) <= this.clock()) {
      this.update({ proposal: Object.freeze({ ...this.state.proposal, status: 'expired' }),
        reviewed: false, confirmation: null, message: 'Proposal expired. It cannot be decided.', error: true });
    }
  };
  private authenticated() {
    this.expire(); return !!this.state.expires && !!this.csrf;
  }
  canDecide = () => !!this.state.expires && Date.parse(this.state.expires) > this.clock()
    && this.state.proposal?.status === 'pending' && Date.parse(this.state.proposal.expires_at) > this.clock()
    && this.state.reviewed && !this.state.busy && !this.state.needsRefresh;
  private async request(route: string, body?: object, csrf = '') {
    const response = await this.fetcher('/api/v1/operator/' + route, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      signal: AbortSignal.timeout(12000), headers: body === undefined ? {} : {
        'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      }, ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    let data;
    try { data = await response.json(); }
    catch { throw new Failure(response.ok ? 502 : response.status); }
    if (!response.ok) throw new Failure(response.status, typeof data?.error === 'string' ? data.error : '');
    return data;
  }
  private session(data: Record<string, unknown>) {
    if (data.authenticated !== true || typeof data.csrf_token !== 'string'
        || !/^[A-Za-z0-9_-]{43}$/.test(data.csrf_token) || typeof data.expires_at !== 'string'
        || !Number.isFinite(Date.parse(data.expires_at)) || Date.parse(data.expires_at) <= this.clock()) throw new Failure(401);
    this.csrf = data.csrf_token; this.update({ expires: data.expires_at, message: 'Operator signed in.', error: false });
  }
  private proposal(data: Record<string, unknown>, id: string): SafeActionProposal {
    if (data.proposal_id !== id || typeof data.title !== 'string' || !Array.isArray(data.items)
        || !data.items.every(item => typeof item === 'string') || typeof data.fingerprint !== 'string'
        || !/^[a-f0-9]{64}$/.test(data.fingerprint) || typeof data.expires_at !== 'string'
        || !Number.isFinite(Date.parse(data.expires_at)) || !['pending','approved','rejected','expired'].includes(String(data.status))) throw new Failure(502);
    return Object.freeze({ proposal_id: id, title: data.title, items: Object.freeze([...data.items]),
      fingerprint: data.fingerprint, expires_at: data.expires_at, status: data.status as SafeActionProposal['status'] });
  }
  private failed(error: unknown, login = false) {
    if (error instanceof Failure && error.code === 'OPERATOR_UNCONFIGURED') {
      this.clear('Local operator authentication is not configured.', true);
    } else if (error instanceof Failure && [401,403].includes(error.status)) {
      this.clear(login ? 'Sign-in failed. Check your credential and local configuration.' : 'Session expired or authorization failed. Sign in again.', true);
    } else if (error instanceof Failure && error.status === 409) {
      this.update({ reviewed: false, confirmation: null, needsRefresh: true,
        message: 'Proposal expired, changed, or was already decided. Reload it before continuing.', error: true });
    } else {
      const message = error instanceof Failure && error.status === 429 ? 'Too many login attempts. Wait a minute.'
        : error instanceof Failure && error.status === 404 ? 'Proposal not found.'
        : error instanceof Failure && error.code === 'OPERATOR_UNCONFIGURED' ? 'Local operator authentication is not configured.'
        : 'Operator backend unavailable. Reload proposal status before retrying a decision.';
      this.update({ reviewed: false, confirmation: null, needsRefresh: true, message, error: true });
    }
  }
  async restore() {
    if (this.state.busy) return;
    this.update({ busy: true });
    try { this.session(await this.request('session')); }
    catch (error) {
      if (error instanceof Failure && error.status === 401) this.clear('Sign in to review a checklist. No operator data has been loaded.');
      else this.failed(error);
    } finally { this.update({ busy: false }); }
  }
  async login(password: string) {
    if (this.state.busy) return;
    this.clear('Signing in…'); this.update({ busy: true });
    try { this.session(await this.request('login', { password })); }
    catch (error) { this.failed(error, true); }
    finally { this.update({ busy: false }); }
  }
  async logout() {
    if (this.state.busy || !this.authenticated()) return;
    const token = this.csrf; this.update({ busy: true });
    try { await this.request('logout', {}, token); this.clear('Operator signed out.'); }
    catch { this.clear('Local view cleared; server logout could not be confirmed. Close this browser session or wait for expiry.', true); }
    finally { this.update({ busy: false }); }
  }
  async retrieve(id: string) {
    if (this.state.busy || !this.authenticated()) return;
    this.update({ proposal: null, reviewed: false, confirmation: null, needsRefresh: false });
    if (!UUID.test(id)) { this.update({ message: 'Enter a valid proposal UUID.', error: true }); return; }
    this.update({ busy: true });
    try {
      const proposal = this.proposal(await this.request('proposals/' + id), id);
      if (!this.authenticated()) return;
      this.update({ proposal, message: proposal.status === 'pending' ? 'Review every item and the fingerprint before deciding.' : 'Proposal is ' + proposal.status + '.', error: false });
      this.expire();
    } catch (error) { this.failed(error); }
    finally { this.update({ busy: false }); }
  }
  review(value: boolean) {
    this.expire();
    if (!this.state.busy && this.state.expires && this.state.proposal?.status === 'pending' && !this.state.needsRefresh) {
      this.update({ reviewed: value, confirmation: null });
    }
  }
  beginDecision(action: 'approve' | 'reject') {
    this.expire(); if (this.canDecide()) this.update({ confirmation: action });
  }
  cancelDecision() { if (!this.state.busy) this.update({ confirmation: null }); }
  async confirmDecision() {
    this.expire(); if (!this.canDecide() || !this.state.confirmation || !this.state.proposal) return;
    const { proposal, confirmation } = this.state; const token = this.csrf;
    this.update({ busy: true, confirmation: null });
    try {
      const result = this.proposal(await this.request('proposals/' + proposal.proposal_id + '/' + confirmation,
        { fingerprint: proposal.fingerprint }, token), proposal.proposal_id);
      if (!this.authenticated()) return;
      if (result.fingerprint !== proposal.fingerprint || result.status !== (confirmation === 'approve' ? 'approved' : 'rejected')) throw new Failure(502);
      this.update({ proposal: result, reviewed: false, message: confirmation === 'approve'
        ? 'Checklist approved and saved by the backend.' : 'Proposal rejected. Checklist was not saved.', error: false });
    } catch (error) { this.failed(error); }
    finally { this.update({ busy: false }); }
  }
}
