# -*- coding: utf-8 -*-
"""Optional IDEA demo seed for Kolibri 0.15 (run inside `kolibri shell`).

Creates (idempotently):
  facility  IDEA Demo School
  class     Grade 5
  accounts  admin (facility admin/superuser), teacher1 (coach), learner1-3
            password = <account name> + "911!"  (public IDEA default;
            teachers change it before real use)
  lessons   one per IDEA-DEMO channel (Grade 5 Science, Early Reading, Maths),
            each with up to MAX_RESOURCES available resources, assigned to Grade 5.

Never touches other facilities (e.g. a Duration Test Facility) and never deletes.
Channels that are not imported yet are skipped and reported; re-run after the
IDEA-DEMO disk has been built into Kolibri.
"""
from __future__ import print_function
import json, os
from kolibri.core.auth.models import Facility, FacilityUser, Classroom, Role, Membership
from kolibri.core.auth.constants.role_kinds import ADMIN, COACH
from kolibri.core.content.models import ChannelMetadata, ContentNode
from kolibri.core.lessons.models import Lesson, LessonAssignment

FACILITY = os.environ.get("DEMO_FACILITY", "IDEA Demo School")
CLASS = os.environ.get("DEMO_CLASS", "Grade 5")
SUFFIX = "911!"
MAX_RESOURCES = int(os.environ.get("DEMO_MAX_RESOURCES", "6"))
LESSONS = [
    # (lesson title, channel name on the IDEA-DEMO disk)
    ("Science: plants, animals, earth and sky", "Grade 5 Science"),
    ("Reading: African Storybook stories", "Early Reading"),
    ("Maths: fractions and multiplication", "Maths"),
]

facility = Facility.objects.filter(name=FACILITY).first()
if facility is None:
    facility = Facility.objects.create(name=FACILITY)
    print("created facility", FACILITY)

# No functions here: `kolibri shell` exec()s stdin, and on Python 2 nested
# functions cannot see names defined by that exec. Plain loops only.
classroom, _ = Classroom.objects.get_or_create(name=CLASS, parent=facility)
users = {}
for username, full_name in [("admin", "Demo Admin"), ("teacher1", "Teacher One"),
                            ("learner1", "Learner One"), ("learner2", "Learner Two"),
                            ("learner3", "Learner Three")]:
    u, created = FacilityUser.objects.get_or_create(
        username=username, facility=facility, defaults={"full_name": full_name})
    if created:
        u.set_password(username + SUFFIX)
        u.save()
    users[username] = u

admin = users["admin"]
if not admin.roles.filter(collection=facility, kind=ADMIN).exists():
    facility.add_admin(admin)
try:  # device superuser so admin can manage channels in Device
    from kolibri.core.device.models import DevicePermissions
    DevicePermissions.objects.get_or_create(
        user=admin, defaults={"is_superuser": True, "can_manage_content": True})
except Exception as e:
    print("device permissions skipped:", e)

teacher = users["teacher1"]
if not teacher.roles.filter(collection=classroom, kind=COACH).exists():
    Role.objects.create(user=teacher, collection=classroom, kind=COACH)
    # coaches also need the facility-level coach role to open Coach
    if not teacher.roles.filter(collection=facility, kind=COACH).exists():
        Role.objects.create(user=teacher, collection=facility, kind=COACH)

learners = ["learner1", "learner2", "learner3"]
for name in learners:
    Membership.objects.get_or_create(user=users[name], collection=classroom)

report = {"facility": facility.name, "facility_id": facility.id, "class": classroom.name,
          "accounts": ["admin", "teacher1"] + learners, "lessons": [], "skipped": []}
for title, channel_name in LESSONS:
    ch = ChannelMetadata.objects.filter(name=channel_name).first()
    if ch is None:
        report["skipped"].append({"lesson": title, "reason": "channel %r not imported" % channel_name})
        continue
    leaves = (ContentNode.objects.filter(channel_id=ch.id, available=True)
              .exclude(kind="topic").order_by("lft")[:MAX_RESOURCES])
    resources = [{"contentnode_id": n.id, "content_id": n.content_id, "channel_id": ch.id}
                 for n in leaves]
    if not resources:
        report["skipped"].append({"lesson": title, "reason": "no available resources in %r" % channel_name})
        continue
    lesson, created = Lesson.objects.get_or_create(
        title=title, collection=classroom,
        defaults={"created_by": teacher, "resources": resources, "is_active": True})
    if not created:
        lesson.resources = resources
        lesson.is_active = True
        lesson.save()
    LessonAssignment.objects.get_or_create(
        lesson=lesson, collection=classroom, defaults={"assigned_by": teacher})
    report["lessons"].append({"title": title, "channel": channel_name, "resources": len(resources)})

print("IDEA_DEMO_SEED_JSON=" + json.dumps(report))
