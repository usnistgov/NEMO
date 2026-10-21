/*
 * Example: clock component added to the jumbotron.
 */

$(document).ready(function() {
  var $jumbotron = $('#jumbotron-container');
  
  // Create the clock element and append it
  var $clock = $('<div></div>', {
    id: 'jumbotron-clock'
  });
  $jumbotron.append($jumbotron, $clock);

  // Function to update clock time every second
  function updateClock() {
    var now = new Date();
    $clock.text(
      now.toLocaleTimeString(
        [], 
        { 
          dateStyle: 'short', 
          timeStyle: 'short'
        }
      )
    );
  }

  // Initial call and 1-second interval setup
  updateClock();
  setInterval(updateClock, 1000);
});
