import random
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from app.database import get_db, User, Task, Match
from app.pvp_manager import match_manager
from app.config import _normalize_subject, _normalize_difficulty, _time_limit_by_difficulty
from app.utils.text import strip_source_lines as _strip_source_lines
from app.task_helpers import build_task_title as _build_task_title, resolve_task_reference_answers as _resolve_task_reference_answers
from app.utils.answer import check_user_answer_against_reference as _check_user_answer_against_reference

router = APIRouter()


@router.websocket("/ws/pvp/{user_id}")
async def pvp_websocket(websocket: WebSocket, user_id: int, db: Session = Depends(get_db)):
    await match_manager.connect(websocket, user_id)
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            await websocket.send_json({"error": "Пользователь не найден"})
            return
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "find_match":
                match_manager.add_to_queue(user_id, user.username, user.rating)
                await websocket.send_json({"type": "queue_joined", "message": "Ищем соперника..."})
                match_result = match_manager.find_match(user_id)
                if match_result:
                    player1, player2 = match_result
                    tasks = db.query(Task).all()
                    if not tasks:
                        await websocket.send_json({"error": "Нет доступных задач"})
                        continue
                    task = random.choice(tasks)
                    match_id = match_manager.create_match(player1, player2, task.id)
                    db.add(Match(player1_id=player1["user_id"], player2_id=player2["user_id"],
                                 task_id=task.id, status="active", started_at=datetime.now()))
                    db.commit()
                    match_data = {
                        "type": "match_found", "match_id": match_id,
                        "opponent": player2["username"] if player1["user_id"] == user_id else player1["username"],
                        "task": {"id": task.id,
                                 "title": _build_task_title(task.title, _normalize_subject(task.subject), task.grade, task.topic),
                                 "problem_statement": _strip_source_lines(task.problem_statement or ""),
                                 "difficulty": _normalize_difficulty(task.difficulty),
                                 "points": task.points, "time_limit": _time_limit_by_difficulty(task.difficulty)}
                    }
                    await websocket.send_json(match_data)
                    opponent_id = player2["user_id"] if player1["user_id"] == user_id else player1["user_id"]
                    if opponent_id in match_manager.connections:
                        opp_data = dict(match_data)
                        opp_data["opponent"] = player1["username"] if player2["user_id"] == opponent_id else player2["username"]
                        await match_manager.connections[opponent_id].send_json(opp_data)
                else:
                    await websocket.send_json({"type": "waiting", "message": "Ожидание соперника..."})

            elif action == "submit_answer":
                match_id = data.get("match_id")
                answer = data.get("answer")
                match = match_manager.submit_answer(match_id, user_id, answer)
                if not match:
                    await websocket.send_json({"error": "Матч не найден"})
                    continue
                task = db.query(Task).filter(Task.id == match["task_id"]).first()
                reference_answers, manual_check = _resolve_task_reference_answers(task)
                is_correct = False if manual_check else any(
                    _check_user_answer_against_reference(answer or "", ref)["is_correct"] for ref in reference_answers
                )
                if match["player1"]["user_id"] == user_id:
                    if is_correct:
                        match["player1_score"] = task.points
                else:
                    if is_correct:
                        match["player2_score"] = task.points
                await websocket.send_json({
                    "type": "answer_result", "is_correct": is_correct,
                    "your_score": match["player1_score"] if match["player1"]["user_id"] == user_id else match["player2_score"],
                    "opponent_score": match["player2_score"] if match["player1"]["user_id"] == user_id else match["player1_score"],
                })
                if match["player1_answer"] and match["player2_answer"]:
                    winner_id = None
                    if match["player1_score"] > match["player2_score"]:
                        winner_id = match["player1"]["user_id"]
                    elif match["player2_score"] > match["player1_score"]:
                        winner_id = match["player2"]["user_id"]
                    p1 = db.query(User).filter(User.id == match["player1"]["user_id"]).first()
                    p2 = db.query(User).filter(User.id == match["player2"]["user_id"]).first()
                    K = 32
                    e1 = 1 / (1 + 10 ** ((p2.rating - p1.rating) / 400))
                    e2 = 1 / (1 + 10 ** ((p1.rating - p2.rating) / 400))
                    s1, s2 = (1, 0) if winner_id == p1.id else (0, 1) if winner_id == p2.id else (0.5, 0.5)
                    p1.rating += int(K * (s1 - e1))
                    p2.rating += int(K * (s2 - e2))
                    db_match = db.query(Match).filter(
                        Match.player1_id == match["player1"]["user_id"],
                        Match.player2_id == match["player2"]["user_id"],
                        Match.status == "active"
                    ).first()
                    if db_match:
                        db_match.winner_id = winner_id
                        db_match.player1_score = match["player1_score"]
                        db_match.player2_score = match["player2_score"]
                        db_match.status = "finished"
                        db_match.finished_at = datetime.now()
                    db.commit()
                    result_data = {
                        "type": "match_finished", "winner_id": winner_id,
                        "your_score": match["player1_score"] if match["player1"]["user_id"] == user_id else match["player2_score"],
                        "opponent_score": match["player2_score"] if match["player1"]["user_id"] == user_id else match["player1_score"],
                        "rating_change": int(K * (s1 - e1)) if match["player1"]["user_id"] == user_id else int(K * (s2 - e2)),
                    }
                    await websocket.send_json(result_data)
                    opponent_id = match["player2"]["user_id"] if match["player1"]["user_id"] == user_id else match["player1"]["user_id"]
                    if opponent_id in match_manager.connections:
                        opp_result = dict(result_data)
                        opp_result["your_score"] = match["player2_score"] if match["player2"]["user_id"] == opponent_id else match["player1_score"]
                        opp_result["opponent_score"] = match["player1_score"] if match["player2"]["user_id"] == opponent_id else match["player2_score"]
                        opp_result["rating_change"] = int(K * (s2 - e2)) if match["player2"]["user_id"] == opponent_id else int(K * (s1 - e1))
                        await match_manager.connections[opponent_id].send_json(opp_result)
                    match_manager.finish_match(match_id)
    except WebSocketDisconnect:
        match_manager.disconnect(user_id)
    except Exception as e:
        await websocket.send_json({"error": "Внутренняя ошибка"})
        match_manager.disconnect(user_id)
