# TODO (future, not urgent)

## West-side cameras — glacier.org blocks still to add

The eight west-side NPS cameras are published by this pipeline as of 2026-08-11
(`apgar_mtn`, `apgar_village`, `lake_mcdonald`, `lake_mcdonald2`,
`apgar_visitor_center`, `middle_fork`, `headquarters`, `west_entrance`). What is
left is the website side — each one needs its own block on glacier.org/webcams,
and the copy-paste traps there are: the `alt` and both `title` attributes on the
image, a unique `id` on the image div, that same slug added to `CAMERA_IDS` in the
`glacier-webcams` plugin's `refresh.js`, a unique `countdown` id, and the
sunrise/sunset div ids. Until that is done the processed images are being uploaded
but nothing displays them.

Two entries on the NPS page remain non-candidates: **Many Glacier - 2** still has a
heading and write-up but no image element at all, dead on their side; and **Logan
Pass 2** is `smv_nps.jpg`, already in this pipeline.
