import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  getCurrentAccount,
  testConnection,
  upsertAccount,
  type AccountCreate,
  type AccountRead,
} from "../../lib/api";

type AccountFormState = {
  email: string;
  displayName: string;
  provider: string;
  imapHost: string;
  imapPort: string;
  imapSsl: boolean;
  username: string;
  secret: string;
};

const initialState: AccountFormState = {
  email: "",
  displayName: "",
  provider: "163",
  imapHost: "imap.163.com",
  imapPort: "993",
  imapSsl: true,
  username: "",
  secret: "",
};

function toFormState(account: AccountRead): AccountFormState {
  return {
    email: account.email,
    displayName: account.display_name ?? "",
    provider: account.provider,
    imapHost: account.imap_host ?? "",
    imapPort: account.imap_port ? String(account.imap_port) : "",
    imapSsl: account.imap_ssl,
    username: account.username ?? "",
    secret: "",
  };
}

function applyProviderPreset(
  current: AccountFormState,
  provider: string,
): AccountFormState {
  if (provider === "163") {
    return {
      ...current,
      provider,
      imapHost: "imap.163.com",
      imapPort: "993",
      imapSsl: true,
    };
  }
  if (provider === "qq") {
    return {
      ...current,
      provider,
      imapHost: "imap.qq.com",
      imapPort: "993",
      imapSsl: true,
    };
  }
  return { ...current, provider };
}

function toPayload(form: AccountFormState): AccountCreate {
  return {
    email: form.email.trim(),
    display_name: form.displayName.trim() || null,
    provider: form.provider,
    imap_host: form.imapHost.trim() || null,
    imap_port: form.imapPort ? Number(form.imapPort) : null,
    imap_ssl: form.imapSsl,
    username: form.username.trim() || null,
    secret: form.secret.trim(),
  };
}

export function AccountSetupPage() {
  const accountQuery = useQuery({
    queryKey: ["account"],
    queryFn: getCurrentAccount,
    retry: false,
  });

  const accountMissing =
    accountQuery.error instanceof ApiError && accountQuery.error.status === 404;

  if (accountQuery.isLoading) {
    return <div className="text-sm text-slate-500">读取账号配置...</div>;
  }

  if (accountQuery.error && !accountMissing) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        {accountQuery.error instanceof Error
          ? accountQuery.error.message
          : "读取账号配置失败"}
      </div>
    );
  }

  return (
    <AccountSetupForm
      initialForm={
        accountQuery.data ? toFormState(accountQuery.data) : initialState
      }
    />
  );
}

function AccountSetupForm({
  initialForm,
}: {
  initialForm: AccountFormState;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(initialForm);
  const [message, setMessage] = useState<string | null>(null);

  const saveMutation = useMutation({
    mutationFn: upsertAccount,
    onSuccess: (account) => {
      queryClient.setQueryData(["account"], account);
      setMessage("账号已保存");
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "保存失败");
    },
  });

  const testMutation = useMutation({
    mutationFn: testConnection,
    onSuccess: () => setMessage("连接测试成功"),
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "连接测试失败");
    },
  });

  function updateField<K extends keyof AccountFormState>(
    key: K,
    value: AccountFormState[K],
  ) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    saveMutation.mutate(toPayload(form));
  }

  function handleTestConnection() {
    setMessage(null);
    testMutation.mutate(toPayload(form));
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">账号配置</h1>
        <p className="mt-2 text-sm text-slate-500">
          配置一个 IMAP 账号，授权码会使用 Windows DPAPI 加密保存。
        </p>
      </div>

      <form
        className="space-y-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm"
        onSubmit={handleSubmit}
      >
        <div className="grid gap-5 md:grid-cols-2">
          <label className="space-y-2 text-sm">
            <span className="font-medium text-slate-700">邮箱</span>
            <input
              className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-sky-500"
              value={form.email}
              onChange={(event) => updateField("email", event.target.value)}
              placeholder="you@example.com"
              required
            />
          </label>

          <label className="space-y-2 text-sm">
            <span className="font-medium text-slate-700">显示名</span>
            <input
              className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-sky-500"
              value={form.displayName}
              onChange={(event) =>
                updateField("displayName", event.target.value)
              }
              placeholder="HyMail 用户"
            />
          </label>

          <label className="space-y-2 text-sm">
            <span className="font-medium text-slate-700">提供商</span>
            <select
              className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-sky-500"
              value={form.provider}
              onChange={(event) =>
                setForm(applyProviderPreset(form, event.target.value))
              }
            >
              <option value="163">163 邮箱</option>
              <option value="qq">QQ 邮箱</option>
              <option value="custom">自定义 IMAP</option>
            </select>
          </label>

          <label className="space-y-2 text-sm">
            <span className="font-medium text-slate-700">用户名</span>
            <input
              className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-sky-500"
              value={form.username}
              onChange={(event) => updateField("username", event.target.value)}
              placeholder="默认使用邮箱"
            />
          </label>

          <label className="space-y-2 text-sm">
            <span className="font-medium text-slate-700">IMAP 服务器</span>
            <input
              className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-sky-500"
              value={form.imapHost}
              onChange={(event) => updateField("imapHost", event.target.value)}
              placeholder="imap.example.com"
              required
            />
          </label>

          <label className="space-y-2 text-sm">
            <span className="font-medium text-slate-700">IMAP 端口</span>
            <input
              className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-sky-500"
              value={form.imapPort}
              onChange={(event) => updateField("imapPort", event.target.value)}
              placeholder="993"
              required
            />
          </label>
        </div>

        <label className="flex items-center gap-3 text-sm text-slate-700">
          <input
            type="checkbox"
            checked={form.imapSsl}
            onChange={(event) => updateField("imapSsl", event.target.checked)}
          />
          使用 SSL
        </label>

        <label className="space-y-2 text-sm">
          <span className="font-medium text-slate-700">授权码</span>
          <input
            type="password"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 outline-none focus:border-sky-500"
            value={form.secret}
            onChange={(event) => updateField("secret", event.target.value)}
            placeholder="IMAP 授权码/应用密码"
            required
          />
        </label>

        {message ? (
          <div className="rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">
            {message}
          </div>
        ) : null}

        <div className="flex flex-wrap gap-3">
          <button
            type="submit"
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            disabled={saveMutation.isPending}
          >
            {saveMutation.isPending ? "保存中..." : "保存账号"}
          </button>
          <button
            type="button"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
            onClick={handleTestConnection}
            disabled={testMutation.isPending}
          >
            {testMutation.isPending ? "测试中..." : "测试连接"}
          </button>
        </div>
      </form>
    </div>
  );
}