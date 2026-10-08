---
doc_id: "ap-0209"
container: anti-patterns
platform: android
summary: "后台任务成功后 UI 一直不刷新 — 落库/刷新写在观察流的完成回调里,而该流成功后不会自然结束"
related: [ap-0098]
sedimented_by: auto
---

# NNNN — 后台任务观察流成功后不结束 — 把落库/刷新押在"流结束"上导致 UI 永不更新

- **平台**:Android(后台任务调度框架的任务信息观察流;iOS 同类长驻观察 API 同理)

## ❌ 错误

```kotlin
// 观察后台任务状态,想在"任务结束"后落库并刷新 UI
workObserver(taskId)          // 长驻观察流:任务成功后仍保持活跃,不发终止信号
    .onCompletion {           // ❌ 成功路径永远走不到这里
        repository.save(result)
        refreshUi()
    }
    .collect { info ->
        renderProgress(info)
    }
```

同类写法(把收尾挂在流的终点而非终态事件上):

```kotlin
val finalInfo = workObserver(taskId).first { it.isFinished }  // 可能拿到,但
collectAllThenSave()          // ❌ "collect 返回后再落库" 依赖流会自行结束
```

## 为什么

1. **观察流的生命周期绑定的是"被观察对象存在",不是"任务完成"**。任务调度框架的
   状态观察流在任务成功后仍然是活跃订阅——它随时可能因任务被重新入队、被同 id
   替换、状态被再次查询而继续发射。框架没有义务在成功后 complete 这条流。
2. **"终态事件"和"流终止"是两件事**。前者是数据平面的事实(收到 final/SUCCEEDED
   token),后者是控制平面的事件(collect 返回)。把落库押在后者上,等于假设
   两者必然同时发生;一旦不同时,业务收尾整段不执行,而且**没有异常、没有日志**,
   排查时只看到"任务明明成功了,界面就是不更新"。
3. **单测容易假通过**。fake 的观察流通常发完终态就 close,于是 `onCompletion`
   照常触发,测试全绿;只有接真框架才暴露。

## ✅ 正确

**在收到终态 token 的那一刻当场落库并刷新,不等流结束。**

```kotlin
workObserver(taskId)
    .collect { info ->
        when (info.state) {
            State.RUNNING -> renderProgress(info)
            State.SUCCEEDED -> {
                repository.save(info.output)   // ✅ 收到终态 token 当场落库
                refreshUi()                    // ✅ 当场刷新
                cancelObservation()            // ✅ 需要的话由消费者主动结束订阅
            }
            State.FAILED, State.CANCELLED -> {
                markFailed(info)               // ✅ 失败也是终态,同样当场收尾
                cancelObservation()
            }
            else -> Unit
        }
    }
```

配套要点:

- **落库幂等**。同一终态可能被重复投递(重新订阅、replay、任务被查询),
  写库与刷新必须可重复执行而不产生重复业务副作用。
- **`onCompletion` 仍然保留,但只做本地资源释放**(解锁、清 loading、解绑),
  不承担业务收尾;它覆盖取消与异常路径,是兜底不是主路径。
- **需要"等一个结果"的调用方**,用 `first { it.isTerminal }` 这类显式终态谓词
  取值,而不是 `toList()` / `collect` 返回后再处理。
- **验收必须用真实调度框架跑一次**:提交任务 → 等成功 → 确认库里有记录且界面已刷新;
  fake 流会掩盖这个坑。

## 关联

- 冷流暴露状态但更新链断(同族:对流的热/冷与生命周期语义误判)
- 流式连接三类终止路径与终态闸门(同族:终态事件 ≠ 流终止,收尾职责需按终止路径分层)
