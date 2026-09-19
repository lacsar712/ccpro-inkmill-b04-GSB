<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import type { GrindPass, Mill } from '../lib/types';

  let rows: GrindPass[] = [];
  let mills: Mill[] = [];
  let error = '';
  let editingId: number | null = null;

  function nowLocal(): string {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  }

  let form = {
    millId: '',
    startedAt: nowLocal(),
    passNo: '1',
    mediaType: '0.8mm 锆珠',
    operatorName: '',
  };

  // 结束遍次的小表单
  let endingId: number | null = null;
  let endForm = { endedAt: nowLocal(), durationMin: '' };

  async function load() {
    error = '';
    try {
      [rows, mills] = await Promise.all([
        api<GrindPass[]>('/grind-passes'),
        api<Mill[]>('/mills'),
      ]);
      if (!form.millId) {
        const grinding = mills.find((m) => m.status === 'grinding');
        form.millId = String((grinding ?? mills[0])?.id ?? '');
      }
    } catch (e) {
      error = e instanceof Error ? e.message : '加载失败';
    }
  }

  onMount(load);

  function millLabel(id: number): string {
    const m = mills.find((x) => x.id === id);
    return m ? `${m.millCode} (#${m.id})` : `#${id}`;
  }

  function reset() {
    const grinding = mills.find((m) => m.status === 'grinding');
    form = {
      millId: String((grinding ?? mills[0])?.id ?? ''),
      startedAt: nowLocal(),
      passNo: '1',
      mediaType: '0.8mm 锆珠',
      operatorName: '',
    };
    editingId = null;
  }

  function toLocalInput(iso: string): string {
    const d = new Date(iso.replace(' ', 'T'));
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  }

  function edit(row: GrindPass) {
    editingId = row.id;
    form = {
      millId: String(row.millId),
      startedAt: toLocalInput(row.startedAt),
      passNo: String(row.passNo),
      mediaType: row.mediaType,
      operatorName: row.operatorName,
    };
  }

  // 新建/编辑的都是“进行中”遍次：durationMin 固定传 0，时长结束时由服务端计算
  async function save() {
    error = '';
    const payload = {
      millId: Number(form.millId),
      startedAt: form.startedAt,
      passNo: Number(form.passNo),
      durationMin: 0,
      mediaType: form.mediaType,
      operatorName: form.operatorName,
    };
    try {
      if (editingId) {
        await api(`/grind-passes/${editingId}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
      } else {
        await api('/grind-passes', { method: 'POST', body: JSON.stringify(payload) });
      }
      reset();
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '保存失败';
    }
  }

  function startEnd(row: GrindPass) {
    endingId = row.id;
    endForm = { endedAt: nowLocal(), durationMin: '' };
  }

  async function confirmEnd() {
    if (endingId == null) return;
    error = '';
    const payload: { endedAt: string; durationMin?: number } = {
      endedAt: endForm.endedAt,
    };
    // 可选核对值；留空则完全由服务端按起止时间计算
    if (endForm.durationMin.trim() !== '') {
      payload.durationMin = Number(endForm.durationMin);
    }
    try {
      await api(`/grind-passes/${endingId}/end`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      endingId = null;
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '结束失败';
    }
  }

  async function remove(row: GrindPass) {
    if (!confirm(`确认删除遍次 #${row.passNo}？仅进行中的遍次可删除。`)) return;
    try {
      await api(`/grind-passes/${row.id}`, { method: 'DELETE' });
      if (editingId === row.id) reset();
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '删除失败';
    }
  }
</script>

<header class="page-head">
  <h1>研磨遍次</h1>
  <p>区分进行中与已结束：新建仅记录开始；结束时由服务端按起止时间计算时长（分钟）</p>
</header>

{#if error}
  <div class="err">{error}</div>
{/if}

<section class="panel">
  <h2>{editingId ? '编辑进行中的遍次' : '新建遍次（开始研磨）'}</h2>
  <div class="fields">
    <div class="field">
      <label>研磨机
        <select bind:value={form.millId} disabled={editingId != null}>
          {#each mills as m}
            <option value={String(m.id)} disabled={m.status !== 'grinding'}>
              {m.millCode}{m.status === 'grinding' ? '（研磨中）' : '（非研磨中，不可选）'}
            </option>
          {/each}
        </select>
      </label>
    </div>
    <div class="field"><label>开始时间<input type="datetime-local" bind:value={form.startedAt} /></label></div>
    <div class="field"><label>遍次<input type="number" min="1" step="1" bind:value={form.passNo} /></label></div>
    <div class="field"><label>研磨介质<input bind:value={form.mediaType} /></label></div>
    <div class="field"><label>操作员<input bind:value={form.operatorName} /></label></div>
  </div>
  <p class="hint">新建为进行中遍次（durationMin = 0）；同一研磨机同时只能有一条进行中，且机台须为研磨状态。</p>
  <div class="actions">
    <button class="btn-primary" on:click={save}>{editingId ? '保存' : '开始研磨'}</button>
    {#if editingId}
      <button class="btn-ghost" on:click={reset}>取消</button>
    {/if}
  </div>
</section>

{#if endingId != null}
  <section class="panel end-panel">
    <h2>结束遍次 #{rows.find((r) => r.id === endingId)?.passNo}</h2>
    <div class="fields">
      <div class="field"><label>结束时间<input type="datetime-local" bind:value={endForm.endedAt} /></label></div>
      <div class="field">
        <label>核对时长(分钟，可选)
          <input type="number" min="0" step="0.01" bind:value={endForm.durationMin} placeholder="留空则完全按时间计算" />
        </label>
      </div>
    </div>
    <p class="hint">服务端按 结束时间 − 开始时间 计算时长，结果须 &gt; 0；若填写核对值且与计算值相差超过 1 分钟将被拒绝。</p>
    <div class="actions">
      <button class="btn-primary" on:click={confirmEnd}>确认结束</button>
      <button class="btn-ghost" on:click={() => (endingId = null)}>取消</button>
    </div>
  </section>
{/if}

<section class="panel">
  <table class="data-table">
    <thead>
      <tr>
        <th>ID</th>
        <th>研磨机</th>
        <th>开始</th>
        <th>结束</th>
        <th>状态</th>
        <th>遍次</th>
        <th>分钟</th>
        <th>介质</th>
        <th>操作员</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row}
        <tr class:open-row={row.open}>
          <td>{row.id}</td>
          <td>{millLabel(row.millId)}</td>
          <td>{row.startedAt}</td>
          <td>{row.endedAt ?? '—'}</td>
          <td>
            {#if row.open}
              <span class="badge grinding">进行中</span>
            {:else}
              <span class="badge idle">已结束</span>
            {/if}
          </td>
          <td>{row.passNo}</td>
          <td>{row.open ? '—' : row.durationMin}</td>
          <td>{row.mediaType}</td>
          <td>{row.operatorName}</td>
          <td class="ops">
            {#if row.open}
              <button class="link-btn" on:click={() => startEnd(row)}>结束</button>
              <button class="link-btn" on:click={() => edit(row)}>编辑</button>
              <button class="link-btn danger" on:click={() => remove(row)}>删除</button>
            {:else}
              <span class="muted">已归档</span>
            {/if}
          </td>
        </tr>
      {:else}
        <tr><td colspan="10">暂无数据</td></tr>
      {/each}
    </tbody>
  </table>
</section>

<style>
  .hint {
    margin: 0.6rem 0 0;
    color: var(--steel);
    font-size: 0.82rem;
  }

  .end-panel {
    border-left: 3px solid var(--vermillion-700);
  }

  .open-row td {
    background: rgba(193, 63, 43, 0.06);
  }
</style>
