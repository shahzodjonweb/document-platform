"""Fail-closed teacher artifact roles, including older mislabeled outputs."""

LEARNER_TEACHER_FEATURES=frozenset({
    'teacher.worksheet','teacher.homework','teacher.mcq',
    'teacher.written_test','teacher.reading_level',
})
MIXED_TEACHER_PACKS=frozenset({
    'teacher.variants','teacher.differentiated','teacher.lesson_pack',
})
PUBLIC_ROLES=frozenset({'learner_material','public_preview'})


def artifact_role(feature_id):
    if feature_id=='teacher.answer_key':return 'teacher_key'
    if feature_id.startswith('teacher.'):
        return 'learner_material' if feature_id in LEARNER_TEACHER_FEATURES else 'teacher_feedback'
    return 'learner_material' if feature_id.startswith('school.') else 'user_document'


def may_share_artifact(artifact):
    if artifact.role not in PUBLIC_ROLES:return False
    feature_id=artifact.job.feature_id
    # A role assigned by an older worker must not authorize sharing of private
    # teacher tools. Mixed packs still require a learner role for each artifact.
    return not feature_id.startswith('teacher.') or feature_id in LEARNER_TEACHER_FEATURES|MIXED_TEACHER_PACKS
