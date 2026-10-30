from fastapi import APIRouter

from yasno.api.webapp import materials, profile, quizzes, submissions, teacher

router = APIRouter(prefix="/api/v1", tags=["webapp"])
router.include_router(profile.router)
router.include_router(submissions.router)
router.include_router(quizzes.router)
router.include_router(materials.router)
router.include_router(teacher.router)
