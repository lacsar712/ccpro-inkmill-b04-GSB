<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '../lib/api';
  import type { GrindPass, Mill } from '../lib/types';

  let rows: GrindPass[] = [];
  let mills: Mill[] = [];
  let error = '';
  let editingId: number | null = null;
  let editingMillId: number | null = null;

  function nowLocal(): string {
    const d = new Date();
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  }

  let form = {
    millId: '',
    startedAt: nowLocal(),
    passNo: '1',
    durationMin: '0',
    mediaType: '0.8mm 锆珠',
    operatorName: '',
  };

  // 只有「研磨中且无进行中遍次」的研磨机可新建/挂接遍次（数据来自接口）
  $: selectableMills = mills.filter(
    (m) => m.status === 'grinding' && (!m.hasOpenPass || m.id === editingMillId),
  );

  function pickDefaultMillId(): string {
    const m = mills.find((x) => x.status === 'grinding' && !x.hasOpenPass);
    return m ? String(m.id) : '';
  }

  async function load() {
    error = '';
    try {
      [rows, mills] = await Promise.all([
        api<GrindPass[]>('/grind-passes'),
        api<Mill[]>('/mills'),
      ]);
      const stillValid = mills.some(
        (x) => String(x.id) === form.millId && x.status === 'grinding' && !x.hasOpenPass,
      );
      if (!editingId && !stillValid) {
        form.millId = pickDefaultMillId();
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
    editingId = null;
    editingMillId = null;
    form = {
      millId: pickDefaultMillId(),
      startedAt: nowLocal(),
      passNo: '1',
      durationMin: '0',
      mediaType: '0.8mm 锆珠',
      operatorName: '',
    };
  }

  function toLocalInput(iso: string): string {
    const d = new Date(iso.replace(' ', 'T'));
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 16);
  }

  function edit(row: GrindPass) {
    if (!row.open) return;
    editingId = row.id;
    editingMillId = row.millId;
    form = {
      millId: String(row.millId),
      startedAt: toLocalInput(row.startedAt),
      passNo: String(row.passNo),
      durationMin: String(row.durationMin),
      mediaType: row.mediaType,
      operatorName: row.operatorName,
    };
  }

  async function save() {
    error = '';
    const payload = {
      millId: Number(form.millId),
      startedAt: form.startedAt,
      passNo: Number(form.passNo),
      durationMin: Number(form.durationMin),
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

  async function endPass(row: GrindPass) {
    if (!confirm(`确认结束 ${millLabel(row.millId)} 的第 ${row.passNo} 遍？时长将按起止时间由服务端计算。`)) return;
    error = '';
    try {
      await api(`/grind-passes/${row.id}/end`, {
        method: 'POST',
        body: JSON.stringify({ endedAt: nowLocal() }),
      });
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '结束失败';
    }
  }

  async function remove(id: number) {
    if (!confirm('确认删除该研磨遍次？')) return;
    try {
      await api(`/grind-passes/${id}`, { method: 'DELETE' });
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : '删除失败';
    }
  }
</script>

<header class="page-head">
  <h1>研磨遍次</h1>
  <p>同一研磨机同时仅一条进行中；结束时时长由服务端按起止时间计算</p>
</header>

{#if error}
  <div class="err">{error}</div>
{/if}

<section class="panel">
  <h2>{editingId ? '编辑进行中遍次' : '新建遍次（进行中）'}</h2>
  <div class="fields">
    <div class="field">
      <label>研磨机（研磨中且空闲）
        <select bind:value={form.millId}>
          {#each selectableMills as m}
            <option value={String(m.id)}>{m.millCode}</option>
          {/each}
        </select>
      </label>
    </div>
    <div class="field"><label>开始时间<input type="datetime-local" bind:value={form.startedAt} /></label></div>
    <div class="field"><label>遍次<input type="number" min="1" step="1" bind:value={form.passNo} /></label></div>
    <div class="field"><label>时长(分钟，进行中可为 0)<input type="number" min="0" step="0.01" bind:value={form.durationMin} /></label></div>
    <div class="field"><label>研磨介质<input bind:value={form.mediaType} /></label></div>
    <div class="field"><label>操作员<input bind:value={form.operatorName} /></label></div>
  </div>
  <div class="actions">
    <button class="btn-primary" on:click={save}>{editingId ? '保存' : '创建'}</button>
    {#if editingId}
      <button class="btn-ghost" on:click={reset}>取消</button>
    {/if}
    {#if !editingId && selectableMills.length === 0}
      <span class="muted">暂无可建遍次的研磨机（需状态为研磨中且无进行中遍次）</span>
    {/if}
  </div>
</section>

<section class="panel">
  <table class="data-table">
    <thead>
      <tr>
        <th>ID</th>
        <th>研磨机</th>
        <th>状态</th>
        <th>开始</th>
        <th>结束</th>
        <th>遍次</th>
        <th>分钟</th>
        <th>介质</th>
        <th>操作员</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row}
        <tr>
          <td>{row.id}</td>
          <td>{millLabel(row.millId)}</td>
          <td>
            {#if row.open}
              <span class="badge grinding">进行中</span>
            {:else}
              <span class="badge idle">已结束</span>
            {/if}
          </td>
          <td>{row.startedAt}</td>
          <td>{row.endedAt ?? '—'}</td>
          <td>{row.passNo}</td>
          <td>{row.durationMin}</td>
          <td>{row.mediaType}</td>
          <td>{row.operatorName}</td>
          <td class="ops">
            {#if row.open}
              <button class="link-btn" on:click={() => endPass(row)}>结束</button>
              <button class="link-btn" on:click={() => edit(row)}>编辑</button>
              <button class="link-btn danger" on:click={() => remove(row.id)}>删除</button>
            {:else}
              <span class="muted">—</span>
            {/if}
          </td>
        </tr>
      {:else}
        <tr><td colspan="10">暂无数据</td></tr>
      {/each}
    </tbody>
  </table>
</section>
