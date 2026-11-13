// ============================================================================
// SIID-01 — flat ID-CARD style enclosure for the LilyGO T-A7670E
//
// Layout is SIDE-BY-SIDE, not stacked: the board sits in one bay and the flat
// LiPo lies beside it in a second bay. Nothing is on top of anything else, so
// the whole card is only as thick as its tallest single part (~8-9 mm) instead
// of the ~15 mm a stacked design forces.
//
//    +-------------------------------------------------+
//    |  [ LilyGO T-A7670E board ................... ]  |  <- bay A
//   <-  open end                                       |
//    |  [ flat LiPo ........... ] [ GPS patch ]        |  <- bay B
//    +-------------------------------------------------+
//     ^ this end is OPEN across the board bay, so the board's own
//       Type-C port is reachable. No other holes in the shell.
//
// Open in OpenSCAD (free - openscad.org):
//   part="tray" -> F6 -> File > Export > Export as STL
//   part="lid"  -> F6 -> export
//   part="both" -> F5 to preview them side by side
//
// SIZE REALITY CHECK: the board itself is ~106 mm long, so the finished card
// cannot be smaller than that. It comes out 110.4 x 75.1 mm with the defaults - bigger than a
// credit card (85.6 x 54), but FLAT and card-shaped, worn on a lanyard.
// ============================================================================

/* ================= MEASURE THESE BEFORE PRINTING =================
   [ ] board length / width / height (height = tallest component on it)
   [ ] flat LiPo length / width / thickness
   [ ] GPS patch antenna size
   A case 1 mm too small is wasted plastic. Trust your caliper.

   No USB measurement needed: the charging end of the board bay is left open,
   so the port lines up whatever its exact position.
   ================================================================= */

// -------------------- PARTS --------------------
part          = "both";     // "tray" | "lid" | "both"

// --- LilyGO T-A7670E board (18650 holder removed) ---
board_l       = 106;
board_w       = 33;
board_h       = 6;          // board + tallest component + solder tails

// --- flat LiPo, lying BESIDE the board ---
batt_l        = 60;
batt_w        = 35;
batt_h        = 5;

// --- GPS ceramic patch antenna (sits beside the battery, facing UP) ---
gps_l         = 25;
gps_w         = 25;
gps_h         = 4;

// The flat LTE film antenna is adhesive - stick it inside the lid. It is thin
// enough that it needs no cavity of its own.

// -------------------- FIT & SHELL --------------------
clear         = 0.6;        // slack around each part so it drops in
wall          = 1.6;        // side wall thickness
floor_t       = 1.2;        // base thickness
lid_t         = 1.2;        // lid thickness
divider       = 1.5;        // rib between the two bays
corner_r      = 5;          // card corner radius (a real ID card is ~3.2)

lid_lip_h     = 3;          // depth the lid plug sinks in
lid_clear     = 0.35;       // lid fit slack; raise to ~0.45 if too tight

// -------------------- OPENINGS --------------------
// The charging end of the board bay is left completely OPEN rather than having a
// window cut in it: the Type-C port is mounted on the board's edge, so an open
// end means the cable plugs straight in with no alignment to get wrong.
// Both aerials live INSIDE the card (GPS patch in its own bay, flat LTE film
// stuck to the inside of the lid), so there are no cable exits and no other
// holes anywhere in the shell.
open_end      = true;       // leave the charging end of the board bay open

lanyard       = true;
lanyard_w     = 14;         // lanyard SLOT width (a slot, like a real ID card)
lanyard_h     = 3.2;        // slot height

label_recess  = true;       // shallow recess on the lid for a printed ID insert
label_depth   = 0.6;
label_margin  = 6;

$fn           = 64;

// -------------------- DERIVED --------------------
bayA_w   = board_w + 2*clear;                 // board bay
bayB_w   = max(batt_w, gps_w) + 2*clear;      // battery + GPS bay
inner_x  = max(board_l, batt_l + gps_l + 3) + 2*clear;
inner_y  = bayA_w + divider + bayB_w;
inner_z  = max(board_h, batt_h, gps_h);       // <- the card's thickness driver

outer_x  = inner_x + 2*wall;
outer_y  = inner_y + 2*wall;
tray_h   = floor_t + inner_z;
total_h  = tray_h + lid_t;
inner_r  = max(0.8, corner_r - wall);

// rounded rectangular prism with a corner at the origin
module rbox(x, y, z, r) {
  hull() for (i = [r, x-r], j = [r, y-r])
    translate([i, j, 0]) cylinder(r = r, h = z);
}

module tray() {
  difference() {
    rbox(outer_x, outer_y, tray_h, corner_r);

    // --- bay A: the board ---
    translate([wall, wall, floor_t])
      rbox(inner_x, bayA_w, inner_z + 1, inner_r);

    // --- bay B: flat LiPo ---
    translate([wall, wall + bayA_w + divider, floor_t])
      rbox(batt_l + 2*clear, bayB_w, inner_z + 1, inner_r);

    // --- bay B continued: GPS patch antenna, beside the battery ---
    translate([wall + batt_l + 2*clear + 3, wall + bayA_w + divider, floor_t])
      rbox(gps_l + 2*clear, bayB_w, inner_z + 1, inner_r);

    // --- charging end left fully open across the board bay ---
    // The whole end wall is removed over bay A, so the board's own Type-C port
    // is reachable no matter exactly where it sits along that edge.
    if (open_end)
      translate([-1, wall, floor_t])
        cube([wall + 2, bayA_w, inner_z + 1]);

    // --- lanyard slot, like a real ID card (top edge, centred) ---
    if (lanyard)
      translate([outer_x/2 - lanyard_w/2, outer_y - wall/2 - lanyard_h/2 - 1.4, -1])
        cube([lanyard_w, lanyard_h, tray_h + 2]);
  }
}

module lid() {
  difference() {
    union() {
      rbox(outer_x, outer_y, lid_t, corner_r);
      // plug lip that drops into bay A only (bay B stays clear for the battery)
      translate([wall + lid_clear, wall + lid_clear, -lid_lip_h])
        rbox(inner_x - 2*lid_clear, bayA_w - 2*lid_clear, lid_lip_h + 0.01, inner_r);
    }
    // hollow the lip to save plastic
    translate([wall + lid_clear + 1.4, wall + lid_clear + 1.4, -lid_lip_h])
      rbox(inner_x - 2*lid_clear - 2.8, bayA_w - 2*lid_clear - 2.8, lid_lip_h, 1);

    // shallow recess on the face for a printed ID insert (name, photo, reg no)
    if (label_recess)
      translate([label_margin, label_margin, lid_t - label_depth])
        rbox(outer_x - 2*label_margin, outer_y - 2*label_margin, label_depth + 1, 3);

    // matching lanyard slot
    if (lanyard)
      translate([outer_x/2 - lanyard_w/2, outer_y - wall/2 - lanyard_h/2 - 1.4, -1])
        cube([lanyard_w, lanyard_h, lid_t + 2]);
  }
}

// -------------------- OUTPUT --------------------
if (part == "tray") tray();
else if (part == "lid") translate([0, 0, lid_t]) rotate([180, 0, 0]) lid();
else {
  tray();
  translate([0, outer_y + 12, lid_t]) rotate([180, 0, 0]) lid();
}

echo(str("CARD SIZE: ", outer_x, " x ", outer_y, " x ", total_h, " mm"));
echo(str("(a credit card is 85.6 x 54 x 0.76 mm - the board alone is ", board_l, " mm long)"));
echo(str("Thickness is set by the tallest single part: ", inner_z, " mm"));
