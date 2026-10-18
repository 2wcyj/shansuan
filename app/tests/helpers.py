from app.backend.domain.profile import Profile
def profile(**changes):
    data=dict(sex='女',age=30,height=165,weight=60,sleep_hours=7,exercise_weekly=2,activity='轻度',lifestyle='上班族',goals=['日常营养均衡'],primary_goal='日常营养均衡',health_status='明确无',allergy_status='明确无')
    data.update(changes)
    return Profile.model_validate(data).model_dump(mode='json')
