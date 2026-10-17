import time
from typing import List, Dict, Any, Optional

class VoiceQuizEngine:
    """
    Interactive Voice Quiz & Flashcard Mode (Feature 3.5).
    - Teacher/Study Companion: Asks questions, evaluates spoken answers, and gives instant audio feedback.
    """

    def __init__(self, tts):
        self.tts = tts
        self.is_active = False
        self.questions: List[Dict[str, Any]] = []
        self.current_idx = 0
        self.score = 0

    def start_quiz(self, topic: str, sample_questions: Optional[List[Dict[str, Any]]] = None):
        """Starts an interactive quiz."""
        self.questions = sample_questions or [
            {
                "question": f"Question 1 on {topic}: What is the primary source of energy for Earth?",
                "answers": ["sun", "the sun", "solar energy"]
            },
            {
                "question": "Question 2: What is the powerhouse of the cell?",
                "answers": ["mitochondria", "the mitochondria"]
            },
            {
                "question": "Question 3: What is the boiling point of water in Celsius?",
                "answers": ["100", "100 degrees", "hundred"]
            }
        ]
        self.current_idx = 0
        self.score = 0
        self.is_active = True

        intro = f"Starting your quiz on {topic}. Let's begin!"
        print(f"🎓 [QUIZ] {intro}")
        self.tts.speak(intro)
        time.sleep(1.0)
        self._ask_current_question()

    def _ask_current_question(self):
        if self.current_idx < len(self.questions):
            q_text = self.questions[self.current_idx]["question"]
            self.tts.speak(q_text)
        else:
            self._finish_quiz()

    def submit_answer(self, user_answer: str) -> bool:
        if not self.is_active or self.current_idx >= len(self.questions):
            return False

        q = self.questions[self.current_idx]
        cleaned_user = user_answer.strip().lower()
        accepted = [a.lower() for a in q.get("answers", [])]

        is_correct = any(ans in cleaned_user for ans in accepted)
        if is_correct:
            self.score += 1
            feedback = "Correct! Well done."
        else:
            correct_one = accepted[0]
            feedback = f"Not quite. The correct answer was {correct_one}."

        print(f"🎓 [QUIZ FEEDBACK] {feedback}")
        self.tts.speak(feedback)
        self.current_idx += 1

        if self.current_idx < len(self.questions):
            time.sleep(1.2)
            self._ask_current_question()
        else:
            time.sleep(1.2)
            self._finish_quiz()
        return True

    def _finish_quiz(self):
        total = len(self.questions)
        summary = f"Quiz complete! You scored {self.score} out of {total}."
        print(f"🎓 [QUIZ FINISHED] {summary}")
        self.tts.speak(summary)
        self.is_active = False

    def cancel_quiz(self):
        if self.is_active:
            self.is_active = False
            self.tts.speak("Quiz cancelled.")
