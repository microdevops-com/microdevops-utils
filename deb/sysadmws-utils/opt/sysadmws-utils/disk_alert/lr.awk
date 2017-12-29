# Lots of int() here are overkill, but there seems to be a bug. Sometimes math op = 0, sometimes = like -4.98079e-17
BEGIN {
	FS = "\t"
}
NF == 2 {
	# Shift seconds in file since now
	$1 = -1*(timestamp - $1);
	sum_x += $1;
	sum_y += $2;
	sum_xy += $1*$2;
	sum_x2 += $1*$1;
	counter += 1;
	x[NR] = $1;
	y[NR] = $2;
}
END {
	mean_x = sum_x / counter;
	mean_y = sum_y / counter;
	mean_xy = sum_xy / counter;
	mean_x2 = sum_x2 / counter;
	# Here and further transform scientific notation to decial, scientific notation produces bugs
	mean_diff = sprintf("%.10f", (mean_x2 - (mean_x*mean_x)));
	# Div by 0 check
	if (sprintf("%.10f", mean_diff) == "0.0000000000") {
		angle = "None";
		shift = "None";
		quality = "None";
		predict = "None";
		predict_hms = "None";
	} else {
		angle = sprintf("%.10f", (mean_xy - (mean_x*mean_y)) / (mean_x2 - (mean_x*mean_x)));
		shift = sprintf("%.10f", (mean_y - angle * mean_x));
		for (i = counter; i > 0; i--) {
			ss_total += sprintf("%.10f", (y[i] - mean_y)**2);
			ss_residual += sprintf("%.10f", (y[i] - (angle * x[i] + shift))**2);
		}
		# Div by 0 check
		if (sprintf("%.10f", ss_total) == "0.0000000000") {
			quality = "None";
		} else {
			quality = sprintf("%.10f", 1 - (ss_residual / ss_total));
		}
		# Div by 0 check
		if (sprintf("%.10f", angle) == "0.0000000000") {
			predict = "None";
			predict_hms = "None";
		} else {
			# Predict seconds to y = 100
			predict = int((100 - shift) / angle);
			# Negative predict means that for now 100 should have been appear already
			# Memorize sign for hms display and make positive
			if (predict < 0) {
				predict_tmp = -1 * predict;
				hms_sign = "-";
			} else {
				predict_tmp = predict;
				hms_sign = "";
			}
			# Calculate H:M:S
			predict_h = int(predict_tmp/3600);
			predict_s = int(predict_tmp-(predict_h*3600));
			predict_m = int(predict_s/60);
			predict_s = int(predict_s-(predict_m*60));
			# Add leading zero to M and S
			if (predict_m < 10) {
				predict_m = "0" predict_m;
			}
			if (predict_s < 10) {
				predict_s = "0" predict_s;
			}
			# Make hms text
			predict_hms = hms_sign predict_h ":" predict_m ":" predict_s;
		}
	}
	print("{\"angle\": \"" angle "\", \"shift\": \"" shift "\", \"quality\": \"" quality "\", \"predict seconds\": \"" predict "\", \"predict hms\": \"" predict_hms "\"}");
}
